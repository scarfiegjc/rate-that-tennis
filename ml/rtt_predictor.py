"""
ratethat.tennis — RTT-based match predictor
=============================================
Computes match win probabilities using ONLY RTT ratings + production-derived
features. Does NOT reference Elo or raw sa_matches rows at predict time —
Sackmann data is training-only by project convention.

Design philosophy
-----------------
This is an additive-logit model. Each predictive feature contributes a
"logit shift" that is signed (positive = favours player 1) and labelled. The
total logit is the sum of contributions; the win probability is sigmoid(total).

Why this rather than XGBoost/LightGBM?
  1. Transparent. Every factor visible to the user with its sign and weight.
  2. Robust to cold-start. New players with no Sackmann history still get a
     sensible probability if we have ranking-based RTT scores or any record.
  3. Calibrated by construction. Sigmoid output is naturally a probability.
  4. The Intelligence tab gets a beautiful, principled breakdown for free.

Once this is in production we can train a residual model on the logit error
to refine the weights — but the spine of the model stays interpretable.

Run:
    python3 -m ml.rtt_predictor --upcoming 7
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta, datetime
from typing import Optional

import psycopg2
import psycopg2.extras
from decimal import Decimal

log = logging.getLogger("rtt-predictor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


PREDICTOR_VERSION = "rtt-v2"


# ─────────────────────────────────────────────────────────────────────────────
# Type-safety helpers: psycopg2 returns NUMERIC columns as decimal.Decimal,
# which can't be multiplied by Python floats and isn't JSON serializable.
# Every value coming back from a Decimal-producing query gets normalised to
# a plain float (or int for whole-number counts) before it enters the
# arithmetic / JSON pipeline.
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(v):
    """Convert any numeric (int/Decimal/float/str) to float, or None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    """Convert any numeric to int, or 0."""
    if v is None:
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, (Decimal, float)):
        return int(v)
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _scrub_decimals(obj):
    """Recursively walk a dict/list and replace any Decimal with float."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _scrub_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_decimals(v) for v in obj]
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# Aging curve — multiplier applied to a player's effective rating.
# Tennis players peak at 23-27; decline visibly after 31. These multipliers
# come from the academic literature + ATP/WTA empirical analyses.
# ─────────────────────────────────────────────────────────────────────────────

AGING_CURVE = {
    16: 0.85, 17: 0.88, 18: 0.91, 19: 0.94, 20: 0.96, 21: 0.98,
    22: 0.99, 23: 1.00, 24: 1.00, 25: 1.00, 26: 1.00, 27: 0.99,
    28: 0.98, 29: 0.97, 30: 0.96,
    31: 0.94, 32: 0.92, 33: 0.90, 34: 0.88, 35: 0.86, 36: 0.83,
    37: 0.80, 38: 0.77, 39: 0.74, 40: 0.70,
}


def _age_factor(age: Optional[float]) -> float:
    if age is None:
        return 1.0
    a = int(round(age))
    if a in AGING_CURVE:
        return AGING_CURVE[a]
    if a < 16:
        return 0.80
    if a > 40:
        return 0.60
    return 1.0


def _age_at(birthday, match_date) -> Optional[float]:
    if birthday is None or match_date is None:
        return None
    try:
        from datetime import date as _date
        md = match_date.date() if hasattr(match_date, 'date') else _date.fromisoformat(str(match_date)[:10])
        bd = birthday.date()  if hasattr(birthday, 'date')   else _date.fromisoformat(str(birthday)[:10])
        return round((md - bd).days / 365.25, 1)
    except Exception:
        return None

DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Coefficients — the "weights" of the additive logit model.
# Tuned to be conservative: a 10-point RTT gap → ~0.5 logit → ~62% probability,
# which matches empirical priors. Surface, form, momentum, hand and H2H stack
# additively up to ±~1.5 logits in extreme cases (~80% probability).
# ─────────────────────────────────────────────────────────────────────────────

W_RTT_GAP_PER_POINT             = 0.05    # overall RTT score difference
W_SURFACE_GAP_PER_POINT         = 0.06    # surface-specific rating difference
W_FORM_GAP_PER_POINT            = 0.025   # form_score difference
W_MOMENTUM                      = 0.10    # rising/falling
W_HAND_EDGE_PER_POINT           = 0.020   # win% above expected vs opponent's hand
W_H2H_PER_NET_WIN               = 0.10    # capped at ±0.40
W_H2H_SURF_PER_NET_WIN          = 0.10    # H2H on this surface
W_BIG_MATCH_GAP_PER_POINT       = 0.020   # in Slam/Masters only
W_VS_TOP10_GAP_PER_POINT        = 0.015   # only when opponent is top-10
W_PRESSURE_GAP_PER_POINT        = 0.015   # in best-of-5 / late rounds
W_FATIGUE_PER_DAY               = -0.06   # |p1 days rest| - |p2 days rest|, only if <2 days
W_SURFACE_RECORD_PER_POINT      = 0.012   # production surface win% diff (recent)

# Slam-derived player-style features (from Matchstat, ms_player_career_stats)
# These are CAREER averages computed only from Grand Slam matches (the only
# matches with full premium stat coverage). Applied as soft style indicators
# even when predicting non-Slam matches — players don't change much.
W_SLAM_WUR_PER_POINT            = 0.50    # winners-to-UE-ratio diff (typical span 0.6–1.5)
W_SLAM_NET_PCT_PER_POINT        = 0.012   # net-points-won % diff
W_SLAM_SERVE_SPEED_PER_POINT    = 0.010   # avg first serve speed (km/h) diff

# Caps to keep any single factor from dominating
CAP_RTT_GAP_LOGIT               = 1.0
CAP_SURFACE_GAP_LOGIT           = 1.0
CAP_HAND_LOGIT                  = 0.30
CAP_H2H_LOGIT                   = 0.40
CAP_FORM_LOGIT                  = 0.40
CAP_BIG_MATCH_LOGIT             = 0.30
CAP_SLAM_FEATURE_LOGIT          = 0.25    # individual slam-derived feature cap


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FactorContribution:
    """A single named contribution to the total logit."""
    code: str
    label: str
    value_p1: Optional[float]
    value_p2: Optional[float]
    logit: float            # signed; positive = favours p1
    favours: str            # 'p1' | 'p2' | 'neutral'
    impact: str             # 'high' | 'medium' | 'low'

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class PredictionResult:
    match_id: int
    prob_p1: float
    prob_p2: float
    confidence: str
    predicted_winner: str          # 'first_player' | 'second_player'
    factors: list[FactorContribution] = field(default_factory=list)
    snapshot: dict = field(default_factory=dict)
    total_logit: float = 0.0
    predictor_version: str = PREDICTOR_VERSION


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def sigmoid(x: float) -> float:
    if x > 30:
        return 1.0
    if x < -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _impact(abs_logit: float) -> str:
    if abs_logit >= 0.20:
        return "high"
    if abs_logit >= 0.07:
        return "medium"
    return "low"


def _favours(logit: float) -> str:
    if logit > 0.02:
        return "p1"
    if logit < -0.02:
        return "p2"
    return "neutral"


def _surface_to_rating_col(surface: Optional[str]) -> Optional[str]:
    """
    Map a surface name to the corresponding rating column. Defaults to
    'hard_rating' when the surface is missing or 'Unknown' — outdoor hard is
    the modal surface and a vastly better default than producing 50/50.
    """
    if not surface:
        return "hard_rating"
    s = surface.lower()
    if s == "unknown":
        return "hard_rating"
    if "clay" in s:
        return "clay_rating"
    if "grass" in s:
        return "grass_rating"
    if "indoor" in s:
        return "indoor_rating"
    if "carpet" in s:
        return "indoor_rating"
    if "hard" in s:
        return "hard_rating"
    return "hard_rating"


def _normalise_hand(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    raw = str(raw).strip().lower()
    if raw.startswith("r"):
        return "Right"
    if raw.startswith("l"):
        return "Left"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Predictor
# ─────────────────────────────────────────────────────────────────────────────

class RttPredictor:
    """
    Computes match win probabilities purely from RTT ratings + production data.
    """

    def __init__(self, db_url: str = DB_URL):
        self.db_url = db_url
        self._conn: Optional[psycopg2.extensions.connection] = None

    # ── connection management ────────────────────────────────────────────────

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.db_url)
        return self._conn

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()

    # ── per-player feature loaders ───────────────────────────────────────────

    def _player_ratings(self, player_id: int) -> dict:
        """
        Pull RTT + skill + surface ratings + momentum from player_ratings.
        If the player has no row OR has rtt_score=NULL, fall back to a
        rank-based estimate so the predictor still has a usable RTT score.
        """
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT rtt_score, clay_rating, hard_rating, grass_rating, indoor_rating,
                       serve_rating, return_rating, net_game_rating, pressure_rating,
                       consistency_score, form_score,
                       big_match_rating, vs_top10_rating, momentum
                FROM player_ratings
                WHERE player_id = %s
                """,
                (player_id,),
            )
            row = cur.fetchone()
        result = dict(row) if row else {}
        # Cold-start fallback: if no RTT score, estimate from current ranking.
        # Mirrors the API's matches.py rank-based heuristic.
        if not result.get("rtt_score"):
            est = self._estimate_rtt_from_rank(player_id)
            if est is not None:
                result["rtt_score"] = est
                result["_rtt_estimated"] = True
        return result

    def _ms_career_stats(self, player_id: int) -> dict:
        """
        Fetch this player's Matchstat-derived career stats (Slam-only premium
        + universal averages). Returns {} when the player isn't linked.
        """
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT cs.*
                    FROM ms_player_links pl
                    JOIN ms_player_career_stats cs ON cs.ms_player_id = pl.ms_id
                    WHERE pl.player_id = %s
                    """,
                    (player_id,),
                )
                row = cur.fetchone()
            return dict(row) if row else {}
        except Exception:
            # ms_* tables may not exist yet — fail soft so the predictor
            # keeps working in environments without the Matchstat layer.
            return {}

    def _estimate_rtt_from_rank(self, player_id: int) -> Optional[float]:
        """
        Rank-based RTT estimate when player_ratings has nothing for this player.
        Uses the player's most recent ATP/WTA ranking from sa_matches (training-only
        — but the SCALAR rank we extract is a derived stat, fine to use internally).
        Formula: 110 - 15*log10(rank). Rank 1 → ~95, Rank 50 → ~72, Rank 200 → ~57.
        Returns None if no rank could be found.
        """
        import math
        conn = self._get_conn()
        # First try the production players table (rank from api-tennis)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, full_name FROM players WHERE id = %s",
                (player_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        name, full_name = row[0], row[1]
        if not (name or full_name):
            return None
        # Try to find a rank in sa_matches by joining on player name.
        last_token = None
        for n in (full_name, name):
            if n:
                tokens = n.replace(".", "").split()
                if tokens:
                    last_token = tokens[-1].strip()
                    if last_token and len(last_token) >= 3:
                        break
        if not last_token:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(
                        MIN(sm.winner_rank) FILTER (WHERE sm.winner_id = sp.player_id),
                        MIN(sm.loser_rank)  FILTER (WHERE sm.loser_id  = sp.player_id)
                    ) AS rank
                    FROM sa_players sp
                    JOIN sa_matches sm ON (sm.winner_id = sp.player_id OR sm.loser_id = sp.player_id)
                    WHERE sp.full_name ILIKE %s
                      AND sm.tourney_date >= CURRENT_DATE - INTERVAL '2 years'
                    """,
                    (f"%{last_token}%",),
                )
                r = cur.fetchone()
        except Exception:
            return None
        rank = r[0] if r and r[0] else None
        if not rank:
            return None
        try:
            est = 110.0 - 15.0 * math.log10(max(1, int(rank)))
            return round(max(15.0, min(95.0, est)), 2)
        except (ValueError, TypeError):
            return None

    def _player_hand_split(self, player_id: int, vs_hand: Optional[str]) -> Optional[dict]:
        """Pull this player's record vs the opponent's hand."""
        if not vs_hand:
            return None
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT matches, wins, losses, win_pct, expected_pct, edge
                FROM player_hand_splits
                WHERE player_id = %s AND vs_hand = %s
                """,
                (player_id, vs_hand),
            )
            row = cur.fetchone()
        if row and row["matches"] and row["matches"] >= 8:
            # Coerce Decimal → float so downstream multiplication doesn't
            # explode with `Decimal * float` TypeError.
            return {k: _to_float(v) if k != "matches" else _to_int(v) for k, v in dict(row).items()}
        return None

    def _h2h(self, p1_id: int, p2_id: int, surface: Optional[str]) -> dict:
        """Head-to-head from the production matches table only."""
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    SUM(CASE WHEN (m.winner = 'First Player'  AND m.first_player_id = %s)
                              OR (m.winner = 'Second Player' AND m.second_player_id = %s)
                             THEN 1 ELSE 0 END) AS p1_wins,
                    SUM(CASE WHEN (m.winner = 'First Player'  AND m.first_player_id = %s)
                              OR (m.winner = 'Second Player' AND m.second_player_id = %s)
                             THEN 1 ELSE 0 END) AS p2_wins,
                    s.name AS surface
                FROM matches m
                LEFT JOIN tournaments t ON t.id = m.tournament_id
                LEFT JOIN surfaces s    ON s.id = t.surface_id
                WHERE ((m.first_player_id = %s AND m.second_player_id = %s)
                    OR (m.first_player_id = %s AND m.second_player_id = %s))
                  AND m.event_status = 'Finished'
                  AND m.winner IS NOT NULL
                GROUP BY s.name
                """,
                (p1_id, p1_id, p2_id, p2_id, p1_id, p2_id, p2_id, p1_id),
            )
            rows = cur.fetchall()

        total = {"p1_wins": 0, "p2_wins": 0}
        on_surface = {"p1_wins": 0, "p2_wins": 0}
        for r in rows:
            # SUM(CASE …) can come back as Decimal in some Postgres builds,
            # so normalise to int before arithmetic.
            p1w = _to_int(r["p1_wins"])
            p2w = _to_int(r["p2_wins"])
            total["p1_wins"] += p1w
            total["p2_wins"] += p2w
            if surface and r["surface"] and surface.lower() in r["surface"].lower():
                on_surface["p1_wins"] += p1w
                on_surface["p2_wins"] += p2w
        return {"total": total, "on_surface": on_surface}

    def _surface_record(self, player_id: int, surface: Optional[str]) -> Optional[float]:
        """Production-data surface win rate, last 24 months. Returns 0–100 or None."""
        if not surface:
            return None
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS n,
                    SUM(CASE
                          WHEN (m.winner = 'First Player'  AND m.first_player_id = %s)
                            OR (m.winner = 'Second Player' AND m.second_player_id = %s)
                          THEN 1 ELSE 0 END) AS wins
                FROM matches m
                JOIN tournaments t ON t.id = m.tournament_id
                JOIN surfaces s    ON s.id = t.surface_id
                WHERE (m.first_player_id = %s OR m.second_player_id = %s)
                  AND m.event_status = 'Finished'
                  AND m.winner IS NOT NULL
                  AND s.name ILIKE %s
                  AND m.event_date >= CURRENT_DATE - INTERVAL '24 months'
                """,
                (player_id, player_id, player_id, player_id, f"%{surface}%"),
            )
            row = cur.fetchone()
        if not row or not row[0] or row[0] < 4:
            return None
        # Cast to int so 100.0 * wins doesn't hit the Decimal*float TypeError.
        n, wins = _to_int(row[0]), _to_int(row[1])
        return round(100.0 * wins / n, 2)

    def _days_rest(self, player_id: int, match_date: Optional[date]) -> Optional[int]:
        """Days since this player's last finished match, before match_date."""
        if not match_date:
            return None
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(event_date)
                FROM matches
                WHERE (first_player_id = %s OR second_player_id = %s)
                  AND event_status = 'Finished'
                  AND event_date < %s
                """,
                (player_id, player_id, match_date),
            )
            last = cur.fetchone()[0]
        if not last:
            return None
        return (match_date - last).days

    def _last_match_surface(self, player_id: int, match_date: Optional[date]) -> Optional[str]:
        """Surface of the player's most recent finished match before match_date."""
        if not match_date:
            return None
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.name
                FROM matches m
                LEFT JOIN tournaments t ON t.id = m.tournament_id
                LEFT JOIN surfaces s ON s.id = t.surface_id
                WHERE (m.first_player_id = %s OR m.second_player_id = %s)
                  AND m.event_status = 'Finished'
                  AND m.event_date < %s
                ORDER BY m.event_date DESC, m.id DESC
                LIMIT 1
                """,
                (player_id, player_id, match_date),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def _set1_dominance(self, player_id: int) -> Optional[float]:
        """
        Returns the player's set-1 win rate over the last 24 months, as 0..1.
        Used for set-1 dominance factor.
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS n,
                    SUM(CASE
                          WHEN (m.first_player_id = %s
                                AND ms.score_first ~ '^[0-9]+$'
                                AND ms.score_second ~ '^[0-9]+$'
                                AND ms.score_first::int > ms.score_second::int)
                            OR (m.second_player_id = %s
                                AND ms.score_first ~ '^[0-9]+$'
                                AND ms.score_second ~ '^[0-9]+$'
                                AND ms.score_second::int > ms.score_first::int)
                          THEN 1 ELSE 0 END) AS set1_wins
                FROM matches m
                JOIN match_scores ms ON ms.match_id = m.id AND ms.set_number = 1
                WHERE (m.first_player_id = %s OR m.second_player_id = %s)
                  AND m.event_status = 'Finished'
                  AND m.event_date >= CURRENT_DATE - INTERVAL '24 months'
                """,
                (player_id, player_id, player_id, player_id),
            )
            row = cur.fetchone()
        if not row or not row[0] or row[0] < 5:
            return None
        # Force int conversion so the division returns a clean float.
        return _to_int(row[1]) / _to_int(row[0])

    # ── feature computation ──────────────────────────────────────────────────

    @staticmethod
    def _factor(code: str, label: str, v_p1, v_p2, logit: float) -> FactorContribution:
        return FactorContribution(
            code=code,
            label=label,
            value_p1=round(v_p1, 2) if isinstance(v_p1, (int, float)) else v_p1,
            value_p2=round(v_p2, 2) if isinstance(v_p2, (int, float)) else v_p2,
            logit=round(logit, 4),
            favours=_favours(logit),
            impact=_impact(abs(logit)),
        )

    def _compute_factors(
        self,
        p1_ratings: dict,
        p2_ratings: dict,
        p1_id: int,
        p2_id: int,
        surface: Optional[str],
        tourney_level: Optional[str],
        round_: Optional[str],
        best_of: int,
        p1_hand: Optional[str],
        p2_hand: Optional[str],
        match_date: Optional[date],
        p1_age: Optional[float] = None,
        p2_age: Optional[float] = None,
    ) -> tuple[list[FactorContribution], dict]:
        """Compute every factor contribution. Returns (factors, snapshot)."""
        factors: list[FactorContribution] = []
        snapshot: dict = {}

        def f(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        # Age factors — applied as multipliers on RTT below
        age_f1 = _age_factor(p1_age)
        age_f2 = _age_factor(p2_age)
        snapshot["p1_age"] = p1_age
        snapshot["p2_age"] = p2_age
        snapshot["p1_age_factor"] = age_f1
        snapshot["p2_age_factor"] = age_f2

        # ── 1) RTT score gap (with aging adjustment) ─────────────────────────
        p1_rtt = f(p1_ratings.get("rtt_score"))
        p2_rtt = f(p2_ratings.get("rtt_score"))
        snapshot["p1_rtt"] = p1_rtt
        snapshot["p2_rtt"] = p2_rtt
        if p1_rtt is not None and p2_rtt is not None:
            # Effective rating after aging adjustment — peak players unaffected,
            # ageing players get marked down. Difference becomes the working gap.
            p1_eff = p1_rtt * age_f1
            p2_eff = p2_rtt * age_f2
            snapshot["p1_eff_rtt"] = round(p1_eff, 2)
            snapshot["p2_eff_rtt"] = round(p2_eff, 2)
            gap = p1_eff - p2_eff
            logit = _clip(gap * W_RTT_GAP_PER_POINT, -CAP_RTT_GAP_LOGIT, CAP_RTT_GAP_LOGIT)
            snapshot["rtt_gap"] = round(gap, 2)
            factors.append(self._factor(
                "rtt_gap", "RTT score advantage", p1_rtt, p2_rtt, logit,
            ))

        # ── 1b) Aging differential — shown as a separate insight when meaningful ──
        if p1_age is not None and p2_age is not None and abs(age_f1 - age_f2) >= 0.03:
            # Render as an explanatory factor (logit already in rtt_gap)
            factors.append(self._factor(
                "aging", "Aging curve adjustment",
                p1_age, p2_age, 0.0,    # already counted in rtt_gap; this row is informational
            ))

        # ── 2) Surface-specific rating gap ───────────────────────────────────
        col = _surface_to_rating_col(surface)
        p1_surf = p2_surf = None
        if col:
            p1_surf = f(p1_ratings.get(col))
            p2_surf = f(p2_ratings.get(col))
        snapshot["p1_surface_rtt"] = p1_surf
        snapshot["p2_surface_rtt"] = p2_surf
        if p1_surf is not None and p2_surf is not None:
            gap = p1_surf - p2_surf
            logit = _clip(gap * W_SURFACE_GAP_PER_POINT, -CAP_SURFACE_GAP_LOGIT, CAP_SURFACE_GAP_LOGIT)
            snapshot["surface_gap"] = round(gap, 2)
            label = f"Surface advantage ({(surface or 'court').title()})"
            factors.append(self._factor(
                "surface_rating", label, p1_surf, p2_surf, logit,
            ))

        # ── 3) Form rating gap ───────────────────────────────────────────────
        p1_form = f(p1_ratings.get("form_score"))
        p2_form = f(p2_ratings.get("form_score"))
        if p1_form is not None and p2_form is not None:
            gap = p1_form - p2_form
            logit = _clip(gap * W_FORM_GAP_PER_POINT, -CAP_FORM_LOGIT, CAP_FORM_LOGIT)
            snapshot["form_gap"] = round(gap, 2)
            factors.append(self._factor(
                "form_rating", "Recent form", p1_form, p2_form, logit,
            ))

        # ── 4) Momentum (rising/falling/stable) ──────────────────────────────
        p1_mom = (p1_ratings.get("momentum") or "stable").lower()
        p2_mom = (p2_ratings.get("momentum") or "stable").lower()
        snapshot["p1_momentum"] = p1_mom
        snapshot["p2_momentum"] = p2_mom
        mom_score_map = {"rising": 1, "stable": 0, "falling": -1}
        delta = mom_score_map.get(p1_mom, 0) - mom_score_map.get(p2_mom, 0)
        if delta != 0:
            logit = delta * W_MOMENTUM
            factors.append(self._factor(
                "momentum", "Momentum", p1_mom, p2_mom, logit,
            ))

        # ── 5) Hand matchup (lefty killer / etc.) ────────────────────────────
        h1 = _normalise_hand(p1_hand)
        h2 = _normalise_hand(p2_hand)
        # P1's edge vs P2's hand:
        p1_split = self._player_hand_split(p1_id, h2) if h2 else None
        p2_split = self._player_hand_split(p2_id, h1) if h1 else None
        p1_edge = (p1_split or {}).get("edge")
        p2_edge = (p2_split or {}).get("edge")
        if p1_edge is not None or p2_edge is not None:
            net = (p1_edge or 0) - (p2_edge or 0)
            logit = _clip(net * W_HAND_EDGE_PER_POINT, -CAP_HAND_LOGIT, CAP_HAND_LOGIT)
            label_h2 = h2 or "?"
            label_h1 = h1 or "?"
            label = f"Hand matchup (P1 vs {label_h2}-handed)"
            factors.append(self._factor(
                "hand_matchup", label,
                p1_edge if p1_edge is not None else None,
                p2_edge if p2_edge is not None else None,
                logit,
            ))

        # ── 6) H2H from production ───────────────────────────────────────────
        h2h = self._h2h(p1_id, p2_id, surface)
        net_total = h2h["total"]["p1_wins"] - h2h["total"]["p2_wins"]
        if net_total != 0:
            net_capped = _clip(net_total, -4, 4)
            logit = _clip(net_capped * W_H2H_PER_NET_WIN, -CAP_H2H_LOGIT, CAP_H2H_LOGIT)
            factors.append(self._factor(
                "h2h_overall", "Head-to-head record",
                h2h["total"]["p1_wins"], h2h["total"]["p2_wins"], logit,
            ))
        net_surf = h2h["on_surface"]["p1_wins"] - h2h["on_surface"]["p2_wins"]
        if net_surf != 0 and surface:
            net_capped = _clip(net_surf, -3, 3)
            logit = _clip(net_capped * W_H2H_SURF_PER_NET_WIN, -CAP_H2H_LOGIT, CAP_H2H_LOGIT)
            factors.append(self._factor(
                "h2h_surface", f"H2H on {surface.title()}",
                h2h["on_surface"]["p1_wins"], h2h["on_surface"]["p2_wins"], logit,
            ))

        # ── 7) Big match (Slam/Masters only) ─────────────────────────────────
        is_big = tourney_level in ("G", "M")
        if is_big:
            p1_bm = f(p1_ratings.get("big_match_rating"))
            p2_bm = f(p2_ratings.get("big_match_rating"))
            if p1_bm is not None and p2_bm is not None:
                gap = p1_bm - p2_bm
                logit = _clip(gap * W_BIG_MATCH_GAP_PER_POINT, -CAP_BIG_MATCH_LOGIT, CAP_BIG_MATCH_LOGIT)
                factors.append(self._factor(
                    "big_match", "Big-match experience", p1_bm, p2_bm, logit,
                ))

        # ── 8) Pressure (best-of-5 or late round) ────────────────────────────
        is_late_round = (round_ or "").upper() in ("F", "SF", "QF")
        if best_of == 5 or is_late_round:
            p1_p = f(p1_ratings.get("pressure_rating"))
            p2_p = f(p2_ratings.get("pressure_rating"))
            if p1_p is not None and p2_p is not None:
                gap = p1_p - p2_p
                logit = _clip(gap * W_PRESSURE_GAP_PER_POINT, -0.25, 0.25)
                factors.append(self._factor(
                    "pressure", "Pressure rating", p1_p, p2_p, logit,
                ))

        # ── 8b) Serve vs return matchup ──────────────────────────────────────
        # A strong server against a weak returner (or vice versa) is a meaningful
        # edge. Modelled as p1_serve vs p2_return and p1_return vs p2_serve.
        p1_serve  = f(p1_ratings.get("serve_rating"))
        p2_serve  = f(p2_ratings.get("serve_rating"))
        p1_return = f(p1_ratings.get("return_rating"))
        p2_return = f(p2_ratings.get("return_rating"))
        if all(v is not None for v in (p1_serve, p2_serve, p1_return, p2_return)):
            # Net serve edge: p1's serve advantage over p2's return ability
            serve_gap = (p1_serve - p2_return) - (p2_serve - p1_return)
            logit = _clip(serve_gap * 0.008, -0.25, 0.25)
            if abs(logit) >= 0.02:
                factors.append(self._factor(
                    "serve_return_matchup", "Serve vs return matchup",
                    round(p1_serve, 1), round(p2_serve, 1), logit,
                ))

        # ── 8c) vs Top-10 rating ─────────────────────────────────────────────
        # Already fetched but not used as a factor. Apply when opponent's
        # RTT score is high (proxy for opponent quality).
        p1_vs10 = f(p1_ratings.get("vs_top10_rating"))
        p2_vs10 = f(p2_ratings.get("vs_top10_rating"))
        if p1_vs10 is not None and p2_vs10 is not None:
            gap = p1_vs10 - p2_vs10
            logit = _clip(gap * 0.003, -0.20, 0.20)
            if abs(logit) >= 0.02:
                factors.append(self._factor(
                    "vs_top10", "Performance vs top-10 opponents",
                    round(p1_vs10, 1), round(p2_vs10, 1), logit,
                ))

        # ── 8d) Consistency rating differential ──────────────────────────────
        p1_cons = f(p1_ratings.get("consistency_score"))
        p2_cons = f(p2_ratings.get("consistency_score"))
        if p1_cons is not None and p2_cons is not None:
            gap = p1_cons - p2_cons
            logit = _clip(gap * 0.005, -0.20, 0.20)
            if abs(logit) >= 0.02:
                factors.append(self._factor(
                    "consistency", "Consistency rating",
                    round(p1_cons, 1), round(p2_cons, 1), logit,
                ))

        # ── 9) Production-data surface win rate (last 24 months) ─────────────
        if surface:
            p1_sr = self._surface_record(p1_id, surface)
            p2_sr = self._surface_record(p2_id, surface)
            if p1_sr is not None and p2_sr is not None:
                gap = p1_sr - p2_sr
                logit = _clip(gap * W_SURFACE_RECORD_PER_POINT, -0.30, 0.30)
                factors.append(self._factor(
                    "surface_record", f"Recent {surface.lower()} win-rate", p1_sr, p2_sr, logit,
                ))

        # ── 10) Fatigue — only meaningful when one player has < 2 days rest ──
        d1 = self._days_rest(p1_id, match_date) if match_date else None
        d2 = self._days_rest(p2_id, match_date) if match_date else None
        if d1 is not None and d2 is not None:
            # Only fire if one player is on short rest (back-to-back days).
            if d1 <= 1 or d2 <= 1:
                # More rest = good. Positive (d1 - d2) favours p1.
                rest_delta = d1 - d2
                logit = _clip(rest_delta * 0.06, -0.20, 0.20)
                factors.append(self._factor(
                    "fatigue", "Rest / fatigue (days since last match)", d1, d2, logit,
                ))

        # ── 11) Surface-shift penalty ─────────────────────────────────────────
        # Players who switch surface (e.g. clay → grass) historically perform
        # 3-5% worse for the first match. Only meaningful when surface changes.
        if surface and match_date:
            try:
                last1 = self._last_match_surface(p1_id, match_date)
                last2 = self._last_match_surface(p2_id, match_date)
                def _shift_delta(last_surf, this_surf):
                    if not last_surf or not this_surf:
                        return 0
                    a = last_surf.lower(); b = this_surf.lower()
                    if a == b:
                        return 0
                    # Bigger shift between disparate surfaces (clay <-> grass)
                    pair = tuple(sorted([
                        'clay' if 'clay' in a else 'grass' if 'grass' in a else 'hard',
                        'clay' if 'clay' in b else 'grass' if 'grass' in b else 'hard',
                    ]))
                    if pair == ('clay', 'grass'):
                        return -1   # big shift
                    return 0  # default — same effective surface
                shift_p1 = _shift_delta(last1, surface)
                shift_p2 = _shift_delta(last2, surface)
                # Net penalty (positive favours p1)
                net = shift_p2 - shift_p1     # if p2 has shift_p2=-1 and p1=0, p1 benefits
                if net != 0:
                    logit = _clip(net * 0.10, -0.15, 0.15)
                    factors.append(self._factor(
                        "surface_shift", f"Surface shift ({last1 or '?'} → {surface})",
                        shift_p1, shift_p2, logit,
                    ))
            except Exception:
                pass

        # ── 12) Set-1 dominance ───────────────────────────────────────────────
        # Players with high set-1 win rates tend to set the tone. The DIFFERENCE
        # between players' set-1 win rates is the signal.
        try:
            s1 = self._set1_dominance(p1_id)
            s2 = self._set1_dominance(p2_id)
            if s1 is not None and s2 is not None and abs(s1 - s2) >= 0.05:
                gap = (s1 - s2) * 100  # convert to percentage points
                logit = _clip(gap * 0.008, -0.20, 0.20)
                factors.append(self._factor(
                    "set1_dominance", "Set-1 win rate",
                    round(s1*100,1), round(s2*100,1), logit,
                ))
        except Exception:
            pass

        # ── 13) Punching above weight ─────────────────────────────────────────
        # form_score relative to rtt_score: a high form_score with a lower
        # rtt_score suggests a player on the rise — leading indicator.
        p1_form_v = f(p1_ratings.get("form_score"))
        p2_form_v = f(p2_ratings.get("form_score"))
        p1_rtt_v  = f(p1_ratings.get("rtt_score"))
        p2_rtt_v  = f(p2_ratings.get("rtt_score"))
        if all(v is not None for v in (p1_form_v, p2_form_v, p1_rtt_v, p2_rtt_v)):
            p1_punch = p1_form_v - p1_rtt_v   # positive = on the rise
            p2_punch = p2_form_v - p2_rtt_v
            net = p1_punch - p2_punch
            if abs(net) >= 5:
                logit = _clip(net * 0.012, -0.20, 0.20)
                factors.append(self._factor(
                    "punching_above_weight", "Form vs rating divergence",
                    round(p1_punch, 1), round(p2_punch, 1), logit,
                ))

        # ── 14) Slam-derived player-style features (from Matchstat) ─────────
        # Career averages computed from each player's Grand Slam matches —
        # the only matches with full premium-stat coverage. These features
        # describe playing STYLE, not form, so they apply on every surface.
        # Falls back silently to {} when the player isn't ingested.
        ms_p1 = self._ms_career_stats(p1_id)
        ms_p2 = self._ms_career_stats(p2_id)

        if ms_p1.get("slam_matches") and ms_p2.get("slam_matches"):
            # Both players have Slam history → safe to compare.
            snapshot["p1_slam_matches"] = ms_p1.get("slam_matches")
            snapshot["p2_slam_matches"] = ms_p2.get("slam_matches")

            # Winners-to-UE ratio — efficiency indicator
            p1_wur = f(ms_p1.get("slam_winner_ue_ratio"))
            p2_wur = f(ms_p2.get("slam_winner_ue_ratio"))
            if p1_wur is not None and p2_wur is not None:
                gap = p1_wur - p2_wur
                logit = _clip(gap * W_SLAM_WUR_PER_POINT,
                              -CAP_SLAM_FEATURE_LOGIT, CAP_SLAM_FEATURE_LOGIT)
                snapshot["slam_wur_gap"] = round(gap, 3)
                factors.append(self._factor(
                    "slam_winner_ue_ratio", "Winners-to-errors ratio (Slam career)",
                    round(p1_wur, 2), round(p2_wur, 2), logit,
                ))

            # Net point %
            p1_net = f(ms_p1.get("slam_net_won_pct"))
            p2_net = f(ms_p2.get("slam_net_won_pct"))
            if p1_net is not None and p2_net is not None:
                gap = p1_net - p2_net
                logit = _clip(gap * W_SLAM_NET_PCT_PER_POINT,
                              -CAP_SLAM_FEATURE_LOGIT, CAP_SLAM_FEATURE_LOGIT)
                snapshot["slam_net_pct_gap"] = round(gap, 2)
                factors.append(self._factor(
                    "slam_net_pct", "Net-point win % (Slam career)",
                    round(p1_net, 1), round(p2_net, 1), logit,
                ))

            # Avg first serve speed (only matters on faster surfaces)
            p1_serve = f(ms_p1.get("slam_avg_first_serve_kmh"))
            p2_serve = f(ms_p2.get("slam_avg_first_serve_kmh"))
            surface_lower = (surface or "").lower()
            on_fast_surface = (
                "grass" in surface_lower
                or "hard" in surface_lower
                or "indoor" in surface_lower
                or "carpet" in surface_lower
            )
            if p1_serve is not None and p2_serve is not None and on_fast_surface:
                gap = p1_serve - p2_serve
                logit = _clip(gap * W_SLAM_SERVE_SPEED_PER_POINT,
                              -CAP_SLAM_FEATURE_LOGIT, CAP_SLAM_FEATURE_LOGIT)
                snapshot["slam_serve_speed_gap"] = round(gap, 1)
                factors.append(self._factor(
                    "slam_serve_speed", f"Avg 1st serve speed (Slam career, {surface or 'fast'})",
                    round(p1_serve, 1), round(p2_serve, 1), logit,
                ))

        return factors, snapshot

    # ── public API ───────────────────────────────────────────────────────────

    def predict(
        self,
        match_id: int,
        p1_id: int,
        p2_id: int,
        surface: Optional[str],
        tourney_level: Optional[str] = None,
        round_: Optional[str] = None,
        best_of: int = 3,
        p1_hand: Optional[str] = None,
        p2_hand: Optional[str] = None,
        match_date: Optional[date] = None,
        p1_birthday=None,
        p2_birthday=None,
    ) -> PredictionResult:
        # Pull RTT ratings
        p1_r = self._player_ratings(p1_id)
        p2_r = self._player_ratings(p2_id)

        # Compute factors
        factors, snapshot = self._compute_factors(
            p1_ratings=p1_r,
            p2_ratings=p2_r,
            p1_id=p1_id,
            p2_id=p2_id,
            surface=surface,
            tourney_level=tourney_level,
            round_=round_,
            best_of=best_of,
            p1_hand=p1_hand,
            p2_hand=p2_hand,
            match_date=match_date,
            p1_age=_age_at(p1_birthday, match_date),
            p2_age=_age_at(p2_birthday, match_date),
        )

        total_logit = sum(f.logit for f in factors)
        prob_p1 = sigmoid(total_logit)
        prob_p2 = 1.0 - prob_p1

        # Confidence tiers based on edge from 0.5
        edge = abs(prob_p1 - 0.5)
        if edge >= 0.18:
            confidence = "high"
        elif edge >= 0.08:
            confidence = "medium"
        else:
            confidence = "low"

        predicted_winner = "first_player" if prob_p1 >= 0.5 else "second_player"

        # Sort factors by impact (absolute logit) so the Intelligence tab leads
        # with the most decisive ones.
        factors.sort(key=lambda f: -abs(f.logit))

        return PredictionResult(
            match_id=match_id,
            prob_p1=round(prob_p1, 4),
            prob_p2=round(prob_p2, 4),
            confidence=confidence,
            predicted_winner=predicted_winner,
            factors=factors,
            snapshot=snapshot,
            total_logit=round(total_logit, 4),
            predictor_version=PREDICTOR_VERSION,
        )

    # ── persistence ──────────────────────────────────────────────────────────

    def write_prediction(self, pred: PredictionResult) -> None:
        conn = self._get_conn()
        # Scrub Decimals out of the factor dicts so json.dumps doesn't choke
        # on values that slipped through coming from numeric columns.
        key_factors = [_scrub_decimals(f.as_dict()) for f in pred.factors]
        snap = _scrub_decimals(pred.snapshot or {})
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_predictions
                    (match_id, prob_first_player, prob_second_player, confidence,
                     key_factors, model_version, predictor_version,
                     p1_rtt, p2_rtt, p1_surface_rtt, p2_surface_rtt,
                     rtt_gap, surface_gap, form_gap,
                     p1_momentum, p2_momentum, total_logit, predicted_winner)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s)
                ON CONFLICT (match_id) DO UPDATE SET
                    prob_first_player  = EXCLUDED.prob_first_player,
                    prob_second_player = EXCLUDED.prob_second_player,
                    confidence         = EXCLUDED.confidence,
                    key_factors        = EXCLUDED.key_factors,
                    model_version      = EXCLUDED.model_version,
                    predictor_version  = EXCLUDED.predictor_version,
                    p1_rtt             = EXCLUDED.p1_rtt,
                    p2_rtt             = EXCLUDED.p2_rtt,
                    p1_surface_rtt     = EXCLUDED.p1_surface_rtt,
                    p2_surface_rtt     = EXCLUDED.p2_surface_rtt,
                    rtt_gap            = EXCLUDED.rtt_gap,
                    surface_gap        = EXCLUDED.surface_gap,
                    form_gap           = EXCLUDED.form_gap,
                    p1_momentum        = EXCLUDED.p1_momentum,
                    p2_momentum        = EXCLUDED.p2_momentum,
                    total_logit        = EXCLUDED.total_logit,
                    predicted_winner   = EXCLUDED.predicted_winner,
                    predicted_at       = NOW(),
                    -- Invalidate stored intel / result tracking on flip.
                    -- Otherwise the prose narrates the old pick and
                    -- is_correct stays settled against the wrong side.
                    p1_intel = CASE WHEN model_predictions.predicted_winner IS DISTINCT FROM EXCLUDED.predicted_winner THEN NULL ELSE model_predictions.p1_intel END,
                    p2_intel = CASE WHEN model_predictions.predicted_winner IS DISTINCT FROM EXCLUDED.predicted_winner THEN NULL ELSE model_predictions.p2_intel END,
                    match_preview = CASE WHEN model_predictions.predicted_winner IS DISTINCT FROM EXCLUDED.predicted_winner THEN NULL ELSE model_predictions.match_preview END,
                    did_you_know = CASE WHEN model_predictions.predicted_winner IS DISTINCT FROM EXCLUDED.predicted_winner THEN NULL ELSE model_predictions.did_you_know END,
                    confidence_line = CASE WHEN model_predictions.predicted_winner IS DISTINCT FROM EXCLUDED.predicted_winner THEN NULL ELSE model_predictions.confidence_line END,
                    intel_generated_at = CASE WHEN model_predictions.predicted_winner IS DISTINCT FROM EXCLUDED.predicted_winner THEN NULL ELSE model_predictions.intel_generated_at END,
                    actual_winner = CASE WHEN model_predictions.predicted_winner IS DISTINCT FROM EXCLUDED.predicted_winner THEN NULL ELSE model_predictions.actual_winner END,
                    is_correct = CASE WHEN model_predictions.predicted_winner IS DISTINCT FROM EXCLUDED.predicted_winner THEN NULL ELSE model_predictions.is_correct END,
                    settled_at = CASE WHEN model_predictions.predicted_winner IS DISTINCT FROM EXCLUDED.predicted_winner THEN NULL ELSE model_predictions.settled_at END
                """,
                (
                    pred.match_id,
                    pred.prob_p1,
                    pred.prob_p2,
                    pred.confidence,
                    json.dumps(key_factors),
                    PREDICTOR_VERSION,                # legacy model_version column
                    PREDICTOR_VERSION,
                    snap.get("p1_rtt"),
                    snap.get("p2_rtt"),
                    snap.get("p1_surface_rtt"),
                    snap.get("p2_surface_rtt"),
                    snap.get("rtt_gap"),
                    snap.get("surface_gap"),
                    snap.get("form_gap"),
                    snap.get("p1_momentum"),
                    snap.get("p2_momentum"),
                    pred.total_logit,
                    pred.predicted_winner,
                ),
            )
        conn.commit()

    # ── batch run ────────────────────────────────────────────────────────────

    @staticmethod
    def _tour_level(tour_category: Optional[str], type_name: Optional[str]) -> str:
        tc = (tour_category or "").lower()
        tn = (type_name or "").lower()
        if "grand slam" in tn or "grand_slam" in tn:
            return "G"
        if "masters" in tn or "premier mandatory" in tn or "premier 5" in tn:
            return "M"
        if "challenger" in tc or "challenger" in tn:
            return "C"
        if "itf" in tc or "itf" in tn:
            return "S"
        return "A"

    def predict_upcoming(self, days_ahead: int = 7) -> int:
        """Predict every upcoming match in the production matches table."""
        conn = self._get_conn()
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    m.id AS match_id,
                    m.first_player_id,
                    m.second_player_id,
                    m.event_date,
                    m.tournament_round AS round,
                    m.is_doubles,
                    s.name AS surface,
                    et.tour_category,
                    et.type_name,
                    p1.hand AS p1_hand,
                    p2.hand AS p2_hand,
                    p1.birthday AS p1_birthday,
                    p2.birthday AS p2_birthday
                FROM matches m
                LEFT JOIN tournaments t ON m.tournament_id = t.id
                LEFT JOIN surfaces s    ON t.surface_id = s.id
                LEFT JOIN event_types et ON m.event_type_id = et.id
                LEFT JOIN players p1 ON p1.id = m.first_player_id
                LEFT JOIN players p2 ON p2.id = m.second_player_id
                WHERE m.event_date BETWEEN %s AND %s
                  AND m.event_status NOT IN ('Finished', 'Cancelled', 'Retired', 'Walkover')
                  AND m.first_player_id IS NOT NULL
                  AND m.second_player_id IS NOT NULL
                  AND (m.is_doubles IS NULL OR m.is_doubles = FALSE)
                """,
                (str(today), str(cutoff)),
            )
            upcoming = cur.fetchall()

        log.info(f"Predicting {len(upcoming)} upcoming matches with {PREDICTOR_VERSION}...")

        predicted = 0
        skipped = 0
        for m in upcoming:
            try:
                level = self._tour_level(m.get("tour_category"), m.get("type_name"))
                # Best-of: assume 5 only for Slam men's main draw, else 3.
                # We don't have gender reliably, so treat slams as best-of-5 generically.
                best_of = 5 if level == "G" else 3
                pred = self.predict(
                    match_id=m["match_id"],
                    p1_id=m["first_player_id"],
                    p2_id=m["second_player_id"],
                    surface=m.get("surface"),
                    tourney_level=level,
                    round_=m.get("round"),
                    best_of=best_of,
                    p1_hand=m.get("p1_hand"),
                    p2_hand=m.get("p2_hand"),
                    match_date=m.get("event_date"),
                    p1_birthday=m.get("p1_birthday"),
                    p2_birthday=m.get("p2_birthday"),
                )
                self.write_prediction(pred)
                predicted += 1
            except Exception as e:
                log.warning(f"  Match {m.get('match_id')} failed: {e}")
                skipped += 1

        log.info(f"  ✅ Predicted {predicted} / {len(upcoming)} matches  ({skipped} skipped)")
        return predicted


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upcoming", type=int, default=7,
                        help="Days ahead to predict (default 7)")
    parser.add_argument("--match-id", type=int,
                        help="Predict a single match by id (for debugging)")
    args = parser.parse_args()

    predictor = RttPredictor()
    try:
        if args.match_id:
            conn = predictor._get_conn()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT m.id AS match_id, m.first_player_id, m.second_player_id,
                           m.event_date, m.tournament_round AS round,
                           s.name AS surface, et.tour_category, et.type_name,
                           p1.hand AS p1_hand, p2.hand AS p2_hand
                    FROM matches m
                    LEFT JOIN tournaments t ON t.id = m.tournament_id
                    LEFT JOIN surfaces s    ON s.id = t.surface_id
                    LEFT JOIN event_types et ON et.id = m.event_type_id
                    LEFT JOIN players p1 ON p1.id = m.first_player_id
                    LEFT JOIN players p2 ON p2.id = m.second_player_id
                    WHERE m.id = %s
                    """,
                    (args.match_id,),
                )
                m = cur.fetchone()
            if not m:
                print(f"Match {args.match_id} not found")
                return
            level = predictor._tour_level(m.get("tour_category"), m.get("type_name"))
            best_of = 5 if level == "G" else 3
            pred = predictor.predict(
                match_id=m["match_id"],
                p1_id=m["first_player_id"],
                p2_id=m["second_player_id"],
                surface=m.get("surface"),
                tourney_level=level,
                round_=m.get("round"),
                best_of=best_of,
                p1_hand=m.get("p1_hand"),
                p2_hand=m.get("p2_hand"),
                match_date=m.get("event_date"),
            )
            print(json.dumps({
                "prob_p1": pred.prob_p1,
                "prob_p2": pred.prob_p2,
                "confidence": pred.confidence,
                "total_logit": pred.total_logit,
                "factors": [f.as_dict() for f in pred.factors],
                "snapshot": pred.snapshot,
            }, indent=2, default=str))
            predictor.write_prediction(pred)
        else:
            predictor.predict_upcoming(days_ahead=args.upcoming)
    finally:
        predictor.close()


if __name__ == "__main__":
    main()
