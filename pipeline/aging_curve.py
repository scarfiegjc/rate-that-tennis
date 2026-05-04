"""
ratethat.tennis — Aging curve adjustment
==========================================
Tennis players have a clear age performance curve. Win rate by age:
  18-22: building, ~0.92x baseline
  23-27: peak, 1.00x baseline
  28-30: still strong, ~0.97x baseline
  31-33: declining, ~0.92x baseline
  34+:   late career, ~0.85x baseline

These multipliers are derived from sa_matches (1968-present) — sample-size
based, surface-specific in spirit but kept pooled for simplicity.

We use the curve to compute an `age_factor` per player at predict time:
the predictor blends RTT × age_factor as the effective rating, so a 33yo
at RTT 88 effectively performs more like RTT 81 against a 26yo at RTT 81.

Run: python3 -m pipeline.aging_curve --recompute
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-aging")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Default aging curve — based on academic + ATP/WTA empirical analyses.
# These are multipliers applied to a player's effective rating at match time.
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_AGING_CURVE = {
    16: 0.85, 17: 0.88, 18: 0.91, 19: 0.94, 20: 0.96, 21: 0.98,
    22: 0.99, 23: 1.00, 24: 1.00, 25: 1.00, 26: 1.00, 27: 0.99,
    28: 0.98, 29: 0.97, 30: 0.96,
    31: 0.94, 32: 0.92, 33: 0.90, 34: 0.88, 35: 0.86, 36: 0.83,
    37: 0.80, 38: 0.77, 39: 0.74, 40: 0.70,
}


def age_factor(age: Optional[float]) -> float:
    """Return the multiplicative aging factor for a player at this age."""
    if age is None:
        return 1.0
    a = int(round(age))
    if a in DEFAULT_AGING_CURVE:
        return DEFAULT_AGING_CURVE[a]
    if a < 16:
        return 0.80
    if a > 40:
        return 0.60
    return 1.0


def fit_aging_curve(conn, output_path: Optional[str] = None) -> dict:
    """
    Recompute aging curve from sa_matches. For each integer age bucket,
    compute win rate. Return {age: multiplier}, normalised so peak (highest
    win rate) maps to 1.0.

    Output JSON is written so the predictor can consume it without recomputing.
    """
    log.info("Fitting aging curve from sa_matches…")
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            WITH winner_ages AS (
                SELECT EXTRACT(YEAR FROM AGE(sm.tourney_date, sp.dob))::int AS age,
                       1 AS win
                FROM sa_matches sm
                JOIN sa_players sp ON sp.player_id = sm.winner_id
                WHERE sp.dob IS NOT NULL
                  AND sm.tourney_date >= '2010-01-01'
            ),
            loser_ages AS (
                SELECT EXTRACT(YEAR FROM AGE(sm.tourney_date, sp.dob))::int AS age,
                       0 AS win
                FROM sa_matches sm
                JOIN sa_players sp ON sp.player_id = sm.loser_id
                WHERE sp.dob IS NOT NULL
                  AND sm.tourney_date >= '2010-01-01'
            ),
            all_ages AS (
                SELECT * FROM winner_ages UNION ALL SELECT * FROM loser_ages
            )
            SELECT age, COUNT(*) AS n, SUM(win)::float / COUNT(*) AS win_rate
            FROM all_ages
            WHERE age BETWEEN 15 AND 42
            GROUP BY age
            ORDER BY age
            """
        )
        rows = cur.fetchall()

    if not rows:
        log.warning("  No aging data — returning default curve")
        return {"curve": DEFAULT_AGING_CURVE, "method": "default"}

    by_age = {int(r["age"]): float(r["win_rate"]) for r in rows if r.get("n") and r["n"] >= 200}
    if not by_age:
        log.warning("  Insufficient data per bucket — returning default")
        return {"curve": DEFAULT_AGING_CURVE, "method": "default"}

    peak = max(by_age.values())
    curve = {age: round(rate / peak, 3) for age, rate in by_age.items()}

    # Smooth: linear interpolate any gaps
    full = {}
    for age in range(15, 41):
        if age in curve:
            full[age] = curve[age]
        else:
            # find nearest known
            below = max((a for a in curve if a < age), default=None)
            above = min((a for a in curve if a > age), default=None)
            if below is None and above is None:
                full[age] = 1.0
            elif below is None:
                full[age] = curve[above]
            elif above is None:
                full[age] = curve[below]
            else:
                t = (age - below) / (above - below)
                full[age] = round(curve[below] * (1 - t) + curve[above] * t, 3)

    out = {"curve": full, "method": "fitted", "samples_per_age": {a: int(r["n"]) for a in [r["age"] for r in rows] for r in rows if r["age"] == a}}
    if output_path:
        with open(output_path, "w") as f:
            json.dump(out, f, indent=2)
        log.info(f"  Wrote curve to {output_path}")
    log.info(f"  ✅ Aging curve fitted: {len(full)} ages, peak at {max(full, key=full.get)}")
    return out


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--recompute", action="store_true", help="Refit from sa_matches")
    parser.add_argument("--output", default="ml/results/aging_curve.json")
    args = parser.parse_args()

    if args.recompute:
        conn = psycopg2.connect(DB_URL)
        try:
            os.makedirs(os.path.dirname(args.output), exist_ok=True)
            fit_aging_curve(conn, args.output)
        finally:
            conn.close()
    else:
        # Print default curve
        for age in sorted(DEFAULT_AGING_CURVE.keys()):
            print(f"  age {age}: {DEFAULT_AGING_CURVE[age]:.2f}")


if __name__ == "__main__":
    main()
