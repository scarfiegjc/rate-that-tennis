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

log = logging.getLogger("rtt-predictor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


PREDICTOR_VERSION = "rtt-v1"

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

# Caps to keep any single factor from dominating
CAP_RTT_GAP_LOGIT               = 1.0
CAP_SURFACE_GAP_LOGIT           = 1.0
CAP_HAND_LOGIT                  = 0.30
CAP_H2H_LOGIT                   = 0.40
CAP_FORM_LOGIT                  = 0.40
CAP_BIG_MATCH_LOGIT             = 0.30


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
    if not surface:
        return None
    s = surface.lower()
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
    return None


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
        """Pull RTT + skill + surface ratings + momentum from player_ratings."""
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
        return dict(row) if row else {}

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
            return dict(row)
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
            p1w = r["p1_wins"] or 0
            p2w = r["p2_wins"] or 0
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
        n, wins = row[0], (row[1] or 0)
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

        # ── 1) RTT score gap (the headline) ──────────────────────────────────
        p1_rtt = f(p1_ratings.get("rtt_score"))
        p2_rtt = f(p2_ratings.get("rtt_score"))
        snapshot["p1_rtt"] = p1_rtt
        snapshot["p2_rtt"] = p2_rtt
        if p1_rtt is not None and p2_rtt is not None:
            gap = p1_rtt - p2_rtt
            logit = _clip(gap * W_RTT_GAP_PER_POINT, -CAP_RTT_GAP_LOGIT, CAP_RTT_GAP_LOGIT)
            snapshot["rtt_gap"] = round(gap, 2)
            factors.append(self._factor(
                "rtt_gap", "RTT score advantage", p1_rtt, p2_rtt, logit,
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
        key_factors = [f.as_dict() for f in pred.factors]
        snap = pred.snapshot or {}
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
                    predicted_at       = NOW()
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
                    p2.hand AS p2_hand
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
