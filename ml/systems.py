"""
ratethat.tennis — Systems engine
=================================
Evaluates every upcoming match against a battery of bettor-friendly systems.
Each system is a heuristic that picks one player when its conditions fire,
records the pick with a snapshot, and waits for the result so we can track
accuracy and ROI.

This is where the user-facing 'systems' (Surface Monster, Lefty Killer, etc.)
live. Adding a new system = adding a class below + a row in the systems table
(seeded in pipeline/predictions_schema.sql).

Run:
    python3 -m ml.systems            # evaluate today + 7 days
    python3 -m ml.systems --upcoming 1
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-systems")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SystemPick:
    system_code: str
    pick: str                  # 'first_player' | 'second_player'
    confidence: str            # 'low' | 'medium' | 'high'
    reason: str                # one-line human-readable
    rationale: dict            # structured for the frontend


@dataclass
class MatchInput:
    match_id: int
    p1_id: int
    p2_id: int
    surface: Optional[str]
    tourney_level: Optional[str]
    round_: Optional[str]
    best_of: int
    p1_hand: Optional[str]
    p2_hand: Optional[str]
    p1_ratings: dict
    p2_ratings: dict
    p1_hand_split_vs_opp: Optional[dict]   # split row vs opponent's hand
    p2_hand_split_vs_opp: Optional[dict]
    prediction: Optional[dict]
    market: dict                            # {p1_odds, p2_odds, impl_p1, impl_p2}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _surface_col(surface: Optional[str]) -> Optional[str]:
    if not surface:
        return None
    s = surface.lower()
    if "clay" in s:
        return "clay_rating"
    if "grass" in s:
        return "grass_rating"
    if "indoor" in s or "carpet" in s:
        return "indoor_rating"
    if "hard" in s:
        return "hard_rating"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Systems
# ─────────────────────────────────────────────────────────────────────────────

class SystemBase:
    code: str = ""

    def evaluate(self, m: MatchInput) -> Optional[SystemPick]:
        raise NotImplementedError


class SurfaceMonster(SystemBase):
    """Player elite on this surface (85+) and opponent below average (<70)."""
    code = "surface_monster"

    def evaluate(self, m: MatchInput) -> Optional[SystemPick]:
        col = _surface_col(m.surface)
        if not col:
            return None
        p1 = _f(m.p1_ratings.get(col))
        p2 = _f(m.p2_ratings.get(col))
        if p1 is None or p2 is None:
            return None
        # P1 dominates on this surface
        if p1 >= 85 and p2 <= 70 and (p1 - p2) >= 15:
            return SystemPick(
                self.code, "first_player",
                "high" if (p1 - p2) >= 25 else "medium",
                f"{m.surface or 'Surface'} elite ({p1:.1f}) vs below-average opponent ({p2:.1f}).",
                {"p1_surface": p1, "p2_surface": p2, "surface": m.surface},
            )
        if p2 >= 85 and p1 <= 70 and (p2 - p1) >= 15:
            return SystemPick(
                self.code, "second_player",
                "high" if (p2 - p1) >= 25 else "medium",
                f"{m.surface or 'Surface'} elite ({p2:.1f}) vs below-average opponent ({p1:.1f}).",
                {"p1_surface": p1, "p2_surface": p2, "surface": m.surface},
            )
        return None


class FormSurge(SystemBase):
    """Player rising momentum + form rating 10+ above opponent."""
    code = "form_surge"

    def evaluate(self, m: MatchInput) -> Optional[SystemPick]:
        p1_form = _f(m.p1_ratings.get("form_score"))
        p2_form = _f(m.p2_ratings.get("form_score"))
        p1_mom = (m.p1_ratings.get("momentum") or "").lower()
        p2_mom = (m.p2_ratings.get("momentum") or "").lower()
        if p1_form is None or p2_form is None:
            return None

        if p1_mom == "rising" and (p1_form - p2_form) >= 10:
            return SystemPick(
                self.code, "first_player",
                "high" if (p1_form - p2_form) >= 18 else "medium",
                f"Rising form ({p1_form:.1f}) — {p1_form - p2_form:.1f} points clear of opponent.",
                {"p1_form": p1_form, "p2_form": p2_form, "p1_momentum": p1_mom, "p2_momentum": p2_mom},
            )
        if p2_mom == "rising" and (p2_form - p1_form) >= 10:
            return SystemPick(
                self.code, "second_player",
                "high" if (p2_form - p1_form) >= 18 else "medium",
                f"Rising form ({p2_form:.1f}) — {p2_form - p1_form:.1f} points clear of opponent.",
                {"p1_form": p1_form, "p2_form": p2_form, "p1_momentum": p1_mom, "p2_momentum": p2_mom},
            )
        return None


class HandAdvantage(SystemBase):
    """Player has 7+ point edge above expected vs the opponent's hand."""
    code = "hand_advantage"

    def evaluate(self, m: MatchInput) -> Optional[SystemPick]:
        p1_split = m.p1_hand_split_vs_opp
        p2_split = m.p2_hand_split_vs_opp
        if not (p1_split or p2_split):
            return None

        p1_edge = _f((p1_split or {}).get("edge"))
        p2_edge = _f((p2_split or {}).get("edge"))
        opp_hand_p1 = (m.p2_hand or "?")
        opp_hand_p2 = (m.p1_hand or "?")

        if p1_edge is not None and p1_edge >= 7 and (p2_edge is None or p1_edge > p2_edge + 3):
            return SystemPick(
                self.code, "first_player",
                "high" if p1_edge >= 12 else "medium",
                f"+{p1_edge:.1f} pt edge vs {opp_hand_p1.lower()}-handers (above own baseline).",
                {"p1_edge_vs_opp_hand": p1_edge, "p2_edge_vs_opp_hand": p2_edge,
                 "p1_split": p1_split, "p2_split": p2_split},
            )
        if p2_edge is not None and p2_edge >= 7 and (p1_edge is None or p2_edge > p1_edge + 3):
            return SystemPick(
                self.code, "second_player",
                "high" if p2_edge >= 12 else "medium",
                f"+{p2_edge:.1f} pt edge vs {opp_hand_p2.lower()}-handers (above own baseline).",
                {"p1_edge_vs_opp_hand": p1_edge, "p2_edge_vs_opp_hand": p2_edge,
                 "p1_split": p1_split, "p2_split": p2_split},
            )
        return None


class BigMatchPlayer(SystemBase):
    """Slam/Masters round and player's big_match_rating ≥ 80 and 10+ above opp."""
    code = "big_match_player"

    def evaluate(self, m: MatchInput) -> Optional[SystemPick]:
        if m.tourney_level not in ("G", "M"):
            return None
        p1 = _f(m.p1_ratings.get("big_match_rating"))
        p2 = _f(m.p2_ratings.get("big_match_rating"))
        if p1 is None or p2 is None:
            return None
        if p1 >= 80 and (p1 - p2) >= 10:
            return SystemPick(
                self.code, "first_player",
                "high" if (p1 - p2) >= 18 else "medium",
                f"Big-match rating {p1:.1f} vs {p2:.1f} — built for this stage.",
                {"p1_big_match": p1, "p2_big_match": p2},
            )
        if p2 >= 80 and (p2 - p1) >= 10:
            return SystemPick(
                self.code, "second_player",
                "high" if (p2 - p1) >= 18 else "medium",
                f"Big-match rating {p2:.1f} vs {p1:.1f} — built for this stage.",
                {"p1_big_match": p1, "p2_big_match": p2},
            )
        return None


class UnderdogValue(SystemBase):
    """Model probability beats market implied by 8+ points on the underdog side."""
    code = "underdog_value"

    def evaluate(self, m: MatchInput) -> Optional[SystemPick]:
        if not m.prediction or not m.market:
            return None
        p1 = _f(m.prediction.get("prob_first_player"))
        p2 = _f(m.prediction.get("prob_second_player"))
        ip1 = _f(m.market.get("impl_p1"))
        ip2 = _f(m.market.get("impl_p2"))
        if None in (p1, p2, ip1, ip2):
            return None
        # Edge in percentage points
        e1 = (p1 - ip1) * 100
        e2 = (p2 - ip2) * 100
        # Underdog = the one with implied prob < 0.5
        if ip1 < 0.5 and e1 >= 8 and p1 > ip1:
            return SystemPick(
                self.code, "first_player",
                "high" if e1 >= 14 else "medium",
                f"Model {p1*100:.1f}% vs market {ip1*100:.1f}% — {e1:.1f}pt overlay on the underdog.",
                {"prob_p1": p1, "impl_p1": ip1, "edge_pts": round(e1, 2)},
            )
        if ip2 < 0.5 and e2 >= 8 and p2 > ip2:
            return SystemPick(
                self.code, "second_player",
                "high" if e2 >= 14 else "medium",
                f"Model {p2*100:.1f}% vs market {ip2*100:.1f}% — {e2:.1f}pt overlay on the underdog.",
                {"prob_p2": p2, "impl_p2": ip2, "edge_pts": round(e2, 2)},
            )
        return None


class RttMismatch(SystemBase):
    """Heavy RTT gap (12+ points) — the system's high-confidence baseline."""
    code = "rtt_mismatch"

    def evaluate(self, m: MatchInput) -> Optional[SystemPick]:
        p1 = _f(m.p1_ratings.get("rtt_score"))
        p2 = _f(m.p2_ratings.get("rtt_score"))
        if p1 is None or p2 is None:
            return None
        gap = p1 - p2
        if abs(gap) < 12:
            return None
        if gap > 0:
            return SystemPick(
                self.code, "first_player",
                "high" if gap >= 20 else "medium",
                f"RTT {p1:.1f} vs {p2:.1f} — {gap:.1f}pt class advantage.",
                {"p1_rtt": p1, "p2_rtt": p2, "gap": round(gap, 2)},
            )
        return SystemPick(
            self.code, "second_player",
            "high" if -gap >= 20 else "medium",
            f"RTT {p2:.1f} vs {p1:.1f} — {-gap:.1f}pt class advantage.",
            {"p1_rtt": p1, "p2_rtt": p2, "gap": round(gap, 2)},
        )


class ClutchInDecider(SystemBase):
    """Best-of-5 + pressure_rating 80+ and 10+ points clear."""
    code = "clutch_in_decider"

    def evaluate(self, m: MatchInput) -> Optional[SystemPick]:
        if m.best_of != 5:
            return None
        p1 = _f(m.p1_ratings.get("pressure_rating"))
        p2 = _f(m.p2_ratings.get("pressure_rating"))
        if p1 is None or p2 is None:
            return None
        if p1 >= 80 and (p1 - p2) >= 10:
            return SystemPick(
                self.code, "first_player",
                "high" if (p1 - p2) >= 18 else "medium",
                f"Pressure rating {p1:.1f} vs {p2:.1f} — clutch in best-of-5.",
                {"p1_pressure": p1, "p2_pressure": p2, "best_of": 5},
            )
        if p2 >= 80 and (p2 - p1) >= 10:
            return SystemPick(
                self.code, "second_player",
                "high" if (p2 - p1) >= 18 else "medium",
                f"Pressure rating {p2:.1f} vs {p1:.1f} — clutch in best-of-5.",
                {"p1_pressure": p1, "p2_pressure": p2, "best_of": 5},
            )
        return None


class ClassLock(SystemBase):
    """RTT class gap 20+, surface dominance 10+, model probability 75+."""
    code = "class_lock"

    def evaluate(self, m: MatchInput) -> Optional[SystemPick]:
        p1_rtt = _f(m.p1_ratings.get("rtt_score"))
        p2_rtt = _f(m.p2_ratings.get("rtt_score"))
        if p1_rtt is None or p2_rtt is None:
            return None
        col = _surface_col(m.surface)
        p1_surf = _f(m.p1_ratings.get(col)) if col else None
        p2_surf = _f(m.p2_ratings.get(col)) if col else None
        pred = m.prediction or {}
        p1_prob = _f(pred.get("prob_first_player"))
        p2_prob = _f(pred.get("prob_second_player"))

        def _check(fav_rtt, opp_rtt, fav_surf, opp_surf, fav_prob, side):
            if fav_rtt is None or opp_rtt is None:
                return None
            rtt_gap = fav_rtt - opp_rtt
            if rtt_gap < 20:
                return None
            surf_gap = (fav_surf - opp_surf) if (fav_surf is not None and opp_surf is not None) else None
            if surf_gap is not None and surf_gap < 10:
                return None
            if fav_prob is not None and fav_prob < 0.75:
                return None
            conf = "high" if rtt_gap >= 30 else "medium"
            surf_str = f", surface gap {surf_gap:.1f}" if surf_gap is not None else ""
            prob_str = f", model {fav_prob*100:.0f}%" if fav_prob is not None else ""
            return SystemPick(
                self.code, side, conf,
                f"Class lock: RTT gap {rtt_gap:.1f}{surf_str}{prob_str}.",
                {"fav_rtt": fav_rtt, "opp_rtt": opp_rtt,
                 "surf_gap": surf_gap, "prob": fav_prob},
            )

        return (
            _check(p1_rtt, p2_rtt, p1_surf, p2_surf, p1_prob, "first_player") or
            _check(p2_rtt, p1_rtt, p2_surf, p1_surf, p2_prob, "second_player")
        )


class SurfaceSpecialist(SystemBase):
    """Surface-elite (82+) vs sub-average opponent (62-), surface gap 20+, model 70+."""
    code = "surface_specialist"

    def evaluate(self, m: MatchInput) -> Optional[SystemPick]:
        col = _surface_col(m.surface)
        if not col:
            return None
        p1_surf = _f(m.p1_ratings.get(col))
        p2_surf = _f(m.p2_ratings.get(col))
        if p1_surf is None or p2_surf is None:
            return None
        pred = m.prediction or {}
        p1_prob = _f(pred.get("prob_first_player"))
        p2_prob = _f(pred.get("prob_second_player"))

        def _check(fav_surf, opp_surf, fav_prob, side):
            if fav_surf < 82 or opp_surf > 62:
                return None
            gap = fav_surf - opp_surf
            if gap < 20:
                return None
            if fav_prob is not None and fav_prob < 0.70:
                return None
            conf = "high" if gap >= 30 else "medium"
            return SystemPick(
                self.code, side, conf,
                f"{m.surface or 'Surface'} specialist ({fav_surf:.1f}) vs weak surface opponent ({opp_surf:.1f}), gap {gap:.1f}.",
                {"fav_surf": fav_surf, "opp_surf": opp_surf, "gap": gap, "surface": m.surface, "prob": fav_prob},
            )

        return (
            _check(p1_surf, p2_surf, p1_prob, "first_player") or
            _check(p2_surf, p1_surf, p2_prob, "second_player")
        )


class TripleConvergence(SystemBase):
    """RTT gap 15+, surface gap 10+, form gap 8+ — all three signals favour the same player."""
    code = "triple_convergence"

    def evaluate(self, m: MatchInput) -> Optional[SystemPick]:
        p1_rtt  = _f(m.p1_ratings.get("rtt_score"))
        p2_rtt  = _f(m.p2_ratings.get("rtt_score"))
        p1_form = _f(m.p1_ratings.get("form_score"))
        p2_form = _f(m.p2_ratings.get("form_score"))
        col     = _surface_col(m.surface)
        p1_surf = _f(m.p1_ratings.get(col)) if col else None
        p2_surf = _f(m.p2_ratings.get(col)) if col else None

        if None in (p1_rtt, p2_rtt, p1_form, p2_form):
            return None

        def _check(fav_rtt, opp_rtt, fav_surf, opp_surf, fav_form, opp_form, side):
            rtt_gap  = fav_rtt - opp_rtt
            form_gap = fav_form - opp_form
            if rtt_gap < 15 or form_gap < 8:
                return None
            if fav_surf is not None and opp_surf is not None:
                surf_gap = fav_surf - opp_surf
                if surf_gap < 10:
                    return None
                surf_str = f", surf {surf_gap:.1f}"
            else:
                surf_gap = None
                surf_str = ""
            conf = "high" if (rtt_gap >= 20 and form_gap >= 12) else "medium"
            return SystemPick(
                self.code, side, conf,
                f"Triple convergence: RTT {rtt_gap:.1f}{surf_str}, form {form_gap:.1f} — all point same way.",
                {"rtt_gap": rtt_gap, "surf_gap": surf_gap, "form_gap": form_gap},
            )

        return (
            _check(p1_rtt, p2_rtt, p1_surf, p2_surf, p1_form, p2_form, "first_player") or
            _check(p2_rtt, p1_rtt, p2_surf, p1_surf, p2_form, p1_form, "second_player")
        )


class SmartFavourite(SystemBase):
    """Model probability 70+ AND beats market implied probability by 4+ points."""
    code = "smart_favourite"

    def evaluate(self, m: MatchInput) -> Optional[SystemPick]:
        pred   = m.prediction or {}
        market = m.market or {}
        p1_prob  = _f(pred.get("prob_first_player"))
        p2_prob  = _f(pred.get("prob_second_player"))
        impl_p1  = _f(market.get("impl_p1"))
        impl_p2  = _f(market.get("impl_p2"))

        def _check(our_prob, impl_prob, odds, side):
            if our_prob is None or our_prob < 0.70:
                return None
            if impl_prob is None:
                return None
            edge_pts = (our_prob - impl_prob) * 100  # convert to pct points
            if edge_pts < 4:
                return None
            conf = "high" if edge_pts >= 8 else "medium"
            return SystemPick(
                self.code, side, conf,
                f"Smart favourite: model {our_prob*100:.1f}% vs market {impl_prob*100:.1f}% (+{edge_pts:.1f}pt edge).",
                {"our_prob": our_prob, "impl_prob": impl_prob, "edge_pts": edge_pts, "odds": odds},
            )

        return (
            _check(p1_prob, impl_p1, market.get("odds_p1"), "first_player") or
            _check(p2_prob, impl_p2, market.get("odds_p2"), "second_player")
        )


SYSTEMS: list[SystemBase] = [
    ClassLock(),
    SurfaceSpecialist(),
    TripleConvergence(),
    SmartFavourite(),
]


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────

class SystemsEngine:
    def __init__(self, db_url: str = DB_URL):
        self.db_url = db_url
        self._conn: Optional[psycopg2.extensions.connection] = None
        self._system_id_cache: dict[str, int] = {}

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.db_url)
        return self._conn

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()

    def _system_id(self, code: str) -> Optional[int]:
        if code in self._system_id_cache:
            return self._system_id_cache[code]
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM systems WHERE code = %s", (code,))
            row = cur.fetchone()
        if row:
            self._system_id_cache[code] = row[0]
            return row[0]
        return None

    def _hand_split(self, player_id: int, vs_hand: Optional[str]) -> Optional[dict]:
        if not vs_hand:
            return None
        norm = vs_hand[0].upper() + vs_hand[1:].lower() if vs_hand else None
        if norm not in ("Right", "Left"):
            if vs_hand.lower().startswith("r"):
                norm = "Right"
            elif vs_hand.lower().startswith("l"):
                norm = "Left"
            else:
                return None
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT matches, wins, losses, win_pct, expected_pct, edge
                FROM player_hand_splits
                WHERE player_id = %s AND vs_hand = %s
                """,
                (player_id, norm),
            )
            row = cur.fetchone()
        if row and row["matches"] and row["matches"] >= 8:
            return dict(row)
        return None

    def evaluate_match(self, m_input: MatchInput) -> list[SystemPick]:
        picks = []
        for sys in SYSTEMS:
            try:
                p = sys.evaluate(m_input)
                if p:
                    picks.append(p)
            except Exception as e:
                log.debug(f"  System {sys.code} errored on match {m_input.match_id}: {e}")
        return picks

    def write_picks(self, match_id: int, picks: list[SystemPick],
                    pick_prob_lookup: Optional[dict] = None,
                    market_odds_lookup: Optional[dict] = None) -> int:
        if not picks:
            return 0
        conn = self._get_conn()
        rows = []
        for p in picks:
            sid = self._system_id(p.system_code)
            if sid is None:
                continue
            # Pick-time snapshot of model prob and market odds for this side
            pick_prob = (pick_prob_lookup or {}).get(p.pick) if pick_prob_lookup else None
            market_odds = (market_odds_lookup or {}).get(p.pick) if market_odds_lookup else None
            rows.append((
                sid, match_id, p.pick, p.confidence, p.reason,
                json.dumps(p.rationale),
                pick_prob, market_odds,
            ))
        if not rows:
            return 0
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO system_picks
                    (system_id, match_id, pick, confidence, reason, rationale,
                     pick_prob, market_odds)
                VALUES %s
                ON CONFLICT (system_id, match_id) DO UPDATE SET
                    pick = EXCLUDED.pick,
                    confidence = EXCLUDED.confidence,
                    reason = EXCLUDED.reason,
                    rationale = EXCLUDED.rationale,
                    pick_prob = COALESCE(system_picks.pick_prob, EXCLUDED.pick_prob),
                    market_odds = COALESCE(system_picks.market_odds, EXCLUDED.market_odds)
                """,
                rows,
                page_size=200,
            )
        conn.commit()
        return len(rows)

    def evaluate_upcoming(self, days_ahead: int = 7) -> int:
        conn = self._get_conn()
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    m.id AS match_id,
                    m.first_player_id, m.second_player_id, m.event_date,
                    m.tournament_round AS round, m.is_doubles,
                    s.name AS surface,
                    et.tour_category, et.type_name,
                    p1.hand AS p1_hand, p2.hand AS p2_hand,
                    pr1.rtt_score AS p1_rtt, pr1.clay_rating AS p1_clay,
                    pr1.hard_rating AS p1_hard, pr1.grass_rating AS p1_grass,
                    pr1.indoor_rating AS p1_indoor, pr1.form_score AS p1_form,
                    pr1.momentum AS p1_momentum, pr1.big_match_rating AS p1_big,
                    pr1.pressure_rating AS p1_press,
                    pr2.rtt_score AS p2_rtt, pr2.clay_rating AS p2_clay,
                    pr2.hard_rating AS p2_hard, pr2.grass_rating AS p2_grass,
                    pr2.indoor_rating AS p2_indoor, pr2.form_score AS p2_form,
                    pr2.momentum AS p2_momentum, pr2.big_match_rating AS p2_big,
                    pr2.pressure_rating AS p2_press,
                    mp.prob_first_player, mp.prob_second_player,
                    bo1.decimal_odds AS odds_p1, bo1.implied_prob AS impl_p1,
                    bo2.decimal_odds AS odds_p2, bo2.implied_prob AS impl_p2
                FROM matches m
                LEFT JOIN tournaments t  ON t.id = m.tournament_id
                LEFT JOIN surfaces s     ON s.id = t.surface_id
                LEFT JOIN event_types et ON et.id = m.event_type_id
                LEFT JOIN players p1     ON p1.id = m.first_player_id
                LEFT JOIN players p2     ON p2.id = m.second_player_id
                LEFT JOIN player_ratings pr1 ON pr1.player_id = m.first_player_id
                LEFT JOIN player_ratings pr2 ON pr2.player_id = m.second_player_id
                LEFT JOIN model_predictions mp ON mp.match_id = m.id
                LEFT JOIN LATERAL (
                    SELECT decimal_odds, implied_prob
                    FROM bookmaker_odds
                    WHERE match_id = m.id AND player_ref = 'first_player'
                    ORDER BY fetched_at DESC LIMIT 1
                ) bo1 ON TRUE
                LEFT JOIN LATERAL (
                    SELECT decimal_odds, implied_prob
                    FROM bookmaker_odds
                    WHERE match_id = m.id AND player_ref = 'second_player'
                    ORDER BY fetched_at DESC LIMIT 1
                ) bo2 ON TRUE
                WHERE m.event_date BETWEEN %s AND %s
                  AND m.event_status NOT IN ('Finished', 'Cancelled', 'Retired', 'Walkover')
                  AND m.first_player_id IS NOT NULL
                  AND m.second_player_id IS NOT NULL
                  AND (m.is_doubles IS NULL OR m.is_doubles = FALSE)
                """,
                (str(today), str(cutoff)),
            )
            matches = cur.fetchall()

        log.info(f"Evaluating {len(matches)} matches against {len(SYSTEMS)} systems...")

        total_picks = 0
        for m in matches:
            level = self._tour_level(m.get("tour_category"), m.get("type_name"))
            best_of = 5 if level == "G" else 3
            p1_ratings = {
                "rtt_score": m["p1_rtt"], "clay_rating": m["p1_clay"],
                "hard_rating": m["p1_hard"], "grass_rating": m["p1_grass"],
                "indoor_rating": m["p1_indoor"], "form_score": m["p1_form"],
                "momentum": m["p1_momentum"], "big_match_rating": m["p1_big"],
                "pressure_rating": m["p1_press"],
            }
            p2_ratings = {
                "rtt_score": m["p2_rtt"], "clay_rating": m["p2_clay"],
                "hard_rating": m["p2_hard"], "grass_rating": m["p2_grass"],
                "indoor_rating": m["p2_indoor"], "form_score": m["p2_form"],
                "momentum": m["p2_momentum"], "big_match_rating": m["p2_big"],
                "pressure_rating": m["p2_press"],
            }
            mi = MatchInput(
                match_id=m["match_id"],
                p1_id=m["first_player_id"],
                p2_id=m["second_player_id"],
                surface=m.get("surface"),
                tourney_level=level,
                round_=m.get("round"),
                best_of=best_of,
                p1_hand=m.get("p1_hand"),
                p2_hand=m.get("p2_hand"),
                p1_ratings=p1_ratings,
                p2_ratings=p2_ratings,
                p1_hand_split_vs_opp=self._hand_split(m["first_player_id"], m.get("p2_hand")),
                p2_hand_split_vs_opp=self._hand_split(m["second_player_id"], m.get("p1_hand")),
                prediction={
                    "prob_first_player":  _f(m.get("prob_first_player")),
                    "prob_second_player": _f(m.get("prob_second_player")),
                },
                market={
                    "odds_p1": _f(m.get("odds_p1")), "impl_p1": _f(m.get("impl_p1")),
                    "odds_p2": _f(m.get("odds_p2")), "impl_p2": _f(m.get("impl_p2")),
                },
            )
            picks = self.evaluate_match(mi)
            if not picks:
                continue
            pick_prob_lookup = {
                "first_player": _f(m.get("prob_first_player")),
                "second_player": _f(m.get("prob_second_player")),
            }
            market_odds_lookup = {
                "first_player": _f(m.get("odds_p1")),
                "second_player": _f(m.get("odds_p2")),
            }
            n = self.write_picks(
                m["match_id"], picks,
                pick_prob_lookup=pick_prob_lookup,
                market_odds_lookup=market_odds_lookup,
            )
            total_picks += n

        log.info(f"  ✅ Wrote {total_picks} system picks")
        return total_picks

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upcoming", type=int, default=7)
    args = parser.parse_args()
    eng = SystemsEngine()
    try:
        eng.evaluate_upcoming(days_ahead=args.upcoming)
    finally:
        eng.close()


if __name__ == "__main__":
    main()
