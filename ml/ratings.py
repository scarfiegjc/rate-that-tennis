"""
ratethat.tennis — RTT Rating Engine
====================================
Computes all 13 player ratings from sa_matches (Sackmann historical data)
combined with live matches. Writes to player_ratings and player_ratings_history.

Rating dimensions:
  Surface:  clay_rating, hard_rating, grass_rating, indoor_rating
  Skill:    serve_rating, return_rating, net_game_rating, pressure_rating,
            consistency_rating, form_rating
  Composite: rtt_score, big_match_rating, vs_top10_rating
  Momentum: momentum ('rising' | 'stable' | 'falling')

All ratings normalised to 0–100 (population percentile rank).
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-ratings")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

HALF_LIFE_DAYS = 180          # exponential decay half-life
MAX_MATCH_AGE_DAYS = 1095     # 3 years — older matches excluded
MIN_MATCHES_BIG = 15          # minimum qualifying Slam/Masters matches
MIN_MATCHES_TOP10 = 10        # minimum vs top-10 matches
MIN_ACTIVE_MATCHES = 5        # matches in last 18 months to be "active"
ACTIVE_WINDOW_DAYS = 548      # 18 months

# Tournament level multipliers (same as Elo engine, for consistency)
LEVEL_QUALITY_MULT = {'G': 1.5, 'M': 1.3, 'A': 1.1, 'C': 0.9, 'S': 0.7, 'F': 1.2}

# Rating tier thresholds (from spec)
RATING_TIERS = [
    (90, "Elite",         "#3B6D11"),
    (82, "Strong",        "#639922"),
    (72, "Average",       "#888780"),
    (62, "Below average", "#EF9F27"),
    (0,  "Poor",          "#E24B4A"),
]


# ─────────────────────────────────────────────
# WEIGHTING FUNCTIONS
# ─────────────────────────────────────────────

def decay_weight(match_date: date, reference_date: Optional[date] = None) -> float:
    """Exponential decay with HALF_LIFE_DAYS half-life."""
    if reference_date is None:
        reference_date = date.today()
    days_ago = (reference_date - match_date).days
    if days_ago < 0 or days_ago > MAX_MATCH_AGE_DAYS:
        return 0.0
    lam = np.log(2) / HALF_LIFE_DAYS
    return float(np.exp(-lam * days_ago))


def quality_weight(opponent_rank: Optional[int],
                   tourney_level: Optional[str] = None) -> float:
    """
    Rank-based quality weight in [0.1, 1.0].
    Optionally scaled by tournament level multiplier.
    """
    if opponent_rank is None or opponent_rank > 500:
        q = 0.10
    else:
        q = float(np.clip(1.0 / (1.0 + np.exp(0.02 * (opponent_rank - 30))), 0.10, 1.00))
    mult = LEVEL_QUALITY_MULT.get(tourney_level or '', 1.0)
    return q * mult


def combined_weight(match_date: date, opponent_rank: Optional[int],
                    tourney_level: Optional[str] = None,
                    reference_date: Optional[date] = None) -> float:
    return decay_weight(match_date, reference_date) * quality_weight(opponent_rank, tourney_level)


# ─────────────────────────────────────────────
# SCORE STRING PARSERS
# ─────────────────────────────────────────────

def parse_tiebreak(score: str) -> tuple[int, int]:
    """Return (tiebreaks_won, tiebreaks_played) for the winner."""
    if not score:
        return 0, 0
    sets = score.split()
    won = played = 0
    for s in sets:
        m = re.match(r'(\d+)-(\d+)(?:\((\d+)\))?', s)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        tb = m.group(3)
        if tb is not None:
            played += 1
            if a == 7:
                won += 1  # winner won tiebreak
    return won, played


def parse_games(score: str) -> tuple[int, int]:
    """Return (winner_games, total_games)."""
    if not score:
        return 0, 0
    sets = score.split()
    w_games = t_games = 0
    for s in sets:
        m = re.match(r'(\d+)-(\d+)', s)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        w_games += a
        t_games += a + b
    return w_games, t_games


def parse_deciding_set_win(score: str, best_of: int) -> Optional[bool]:
    """Did this match reach the deciding set? If yes, did the winner win it (always True)."""
    if not score:
        return None
    sets = [s for s in score.split() if re.match(r'\d+-\d+', s)]
    n = len(sets)
    deciding = best_of // 2 + 1
    if n == deciding:
        return True
    return None


def parse_close_final_set(score: str) -> Optional[bool]:
    """Did the final set have 5+ games on loser side? (close match)."""
    if not score:
        return None
    sets = [s for s in score.split() if re.match(r'\d+-\d+', s)]
    if not sets:
        return None
    last = sets[-1]
    m = re.match(r'(\d+)-(\d+)', last)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return b >= 5  # loser had 5+ games in final set


def has_bagel_given(score: str) -> bool:
    """Did the winner give a 6-0 set to the loser?"""
    if not score:
        return False
    for s in score.split():
        if re.match(r'6-0', s):
            return True  # winner served a bagel (loser got 0)
    return False


# ─────────────────────────────────────────────
# NORMALISATION
# ─────────────────────────────────────────────

def normalise_to_population(raw_scores: np.ndarray,
                             player_score: float) -> float:
    """
    Map player_score to 0–100 using percentile rank within raw_scores.
    Slightly compressed so scores never reach exact 0 or 100.
    """
    if len(raw_scores) == 0 or np.isnan(player_score):
        return 50.0
    from scipy.stats import percentileofscore
    pct = percentileofscore(raw_scores, player_score, kind='mean')
    return float(np.clip(pct, 0, 100))


# ─────────────────────────────────────────────
# MATCH RECORD DATACLASS
# ─────────────────────────────────────────────

@dataclass
class MatchRecord:
    match_date: date
    surface: str          # 'Clay' | 'Hard' | 'Grass' | 'Carpet'
    tourney_level: str    # 'G' | 'M' | 'A' | 'C' | 'S'
    won: bool
    opponent_rank: Optional[int]
    minutes: Optional[int]
    best_of: int          # 3 or 5
    score: str
    # Serve stats
    ace: Optional[int] = None
    df: Optional[int] = None
    svpt: Optional[int] = None
    first_in: Optional[int] = None
    first_won: Optional[int] = None
    second_won: Optional[int] = None
    sv_gms: Optional[int] = None
    bp_saved: Optional[int] = None
    bp_faced: Optional[int] = None
    # Opponent serve (for return rating)
    opp_first_in: Optional[int] = None
    opp_first_won: Optional[int] = None
    opp_second_won: Optional[int] = None
    opp_svpt: Optional[int] = None
    opp_bp_faced: Optional[int] = None
    opp_bp_saved: Optional[int] = None


# ─────────────────────────────────────────────
# PER-PLAYER RATING COMPUTER
# ─────────────────────────────────────────────

class PlayerRatingComputer:
    """Computes raw (un-normalised) ratings for one player from their match history."""

    def __init__(self, matches: list[MatchRecord], reference_date: Optional[date] = None):
        self.matches = sorted(matches, key=lambda m: m.match_date)
        self.ref = reference_date or date.today()

    def _w(self, m: MatchRecord) -> float:
        return combined_weight(m.match_date, m.opponent_rank, m.tourney_level, self.ref)

    # ── Surface rating ──────────────────────────────────────────────────

    def surface_rating_raw(self, surface: str) -> Optional[float]:
        ms = [m for m in self.matches if m.surface.lower() == surface.lower()]
        if not ms:
            return None
        total_w = weighted_score = 0.0
        for m in ms:
            w = self._w(m)
            if w == 0:
                continue
            if m.won:
                score = 100.0
            else:
                rank = m.opponent_rank or 300
                score = max(0.0, 50.0 - 0.1 * rank)
            weighted_score += w * score
            total_w += w
        return weighted_score / total_w if total_w > 0 else None

    # ── Serve rating ─────────────────────────────────────────────────────

    def serve_rating_raw(self) -> Optional[float]:
        components = []  # (first_pct, first_won_pct, second_won_pct, bp_save_pct, w)
        for m in self.matches:
            w = self._w(m)
            if w == 0:
                continue
            if None in (m.svpt, m.first_in, m.first_won, m.second_won, m.sv_gms, m.bp_saved, m.bp_faced):
                continue
            if m.svpt <= 0 or m.first_in <= 0:
                continue
            second_in = m.svpt - m.first_in
            if second_in <= 0:
                continue
            fp = m.first_in / m.svpt
            f1w = m.first_won / m.first_in
            f2w = m.second_won / second_in
            bps = m.bp_saved / m.bp_faced if m.bp_faced > 0 else 1.0
            components.append((fp, f1w, f2w, bps, w))

        if not components:
            return None

        total_w = sum(c[4] for c in components)
        if total_w == 0:
            return None
        avg_fp  = sum(c[0] * c[4] for c in components) / total_w
        avg_f1w = sum(c[1] * c[4] for c in components) / total_w
        avg_f2w = sum(c[2] * c[4] for c in components) / total_w
        avg_bps = sum(c[3] * c[4] for c in components) / total_w

        # Blend to [0,1], then scale to raw score
        raw = 0.20 * avg_fp + 0.35 * avg_f1w + 0.25 * avg_f2w + 0.20 * avg_bps
        return raw

    # ── Return rating ────────────────────────────────────────────────────

    def return_rating_raw(self) -> Optional[float]:
        components = []
        for m in self.matches:
            w = self._w(m)
            if w == 0:
                continue
            if None in (m.opp_svpt, m.opp_first_in, m.opp_first_won,
                        m.opp_second_won, m.opp_bp_faced, m.opp_bp_saved):
                continue
            if m.opp_svpt <= 0 or m.opp_first_in <= 0:
                continue
            opp_sec_in = m.opp_svpt - m.opp_first_in
            if opp_sec_in <= 0:
                continue
            opp_f1_pct = m.opp_first_in / m.opp_svpt
            opp_f1w_pct = m.opp_first_won / m.opp_first_in
            opp_f2w_pct = m.opp_second_won / opp_sec_in
            # Return points won = 1 - opponent's serve points won pct
            return_pts = 1.0 - (opp_f1_pct * opp_f1w_pct + (1 - opp_f1_pct) * opp_f2w_pct)
            bp_conv = (m.opp_bp_faced - m.opp_bp_saved) / m.opp_bp_faced if m.opp_bp_faced > 0 else 0.0
            components.append((return_pts, bp_conv, w))

        if not components:
            return None
        total_w = sum(c[2] for c in components)
        if total_w == 0:
            return None
        avg_ret = sum(c[0] * c[2] for c in components) / total_w
        avg_bpc = sum(c[1] * c[2] for c in components) / total_w
        # Approximate return-games-won from win rate (proxy until score parsing)
        win_rate = sum(1 for m in self.matches if m.won) / len(self.matches)
        raw = 0.50 * avg_ret + 0.35 * avg_bpc + 0.15 * win_rate
        return raw

    # ── Pressure rating ──────────────────────────────────────────────────

    def pressure_rating_raw(self) -> Optional[float]:
        tb_won = tb_played = 0
        dec_set_wins = dec_set_played = 0
        close_wins = close_played = 0

        for m in self.matches:
            if decay_weight(m.match_date, self.ref) == 0:
                continue
            tw, tp = parse_tiebreak(m.score)
            tb_won += tw
            tb_played += tp

            ds = parse_deciding_set_win(m.score, m.best_of)
            if ds is not None:
                dec_set_played += 1
                if m.won:
                    dec_set_wins += 1

            close = parse_close_final_set(m.score)
            if close:
                close_played += 1
                if m.won:
                    close_wins += 1

        tb_rate = tb_won / tb_played if tb_played >= 5 else None
        dec_rate = dec_set_wins / dec_set_played if dec_set_played >= 5 else None
        close_rate = close_wins / close_played if close_played >= 3 else None

        vals, weights = [], []
        if tb_rate is not None:
            vals.append(tb_rate); weights.append(0.40)
        if dec_rate is not None:
            vals.append(dec_rate); weights.append(0.35)
        if close_rate is not None:
            vals.append(close_rate); weights.append(0.25)

        if not vals:
            return None
        total_w = sum(weights)
        return sum(v * w for v, w in zip(vals, weights)) / total_w

    # ── Consistency rating ───────────────────────────────────────────────

    def consistency_rating_raw(self) -> Optional[float]:
        # Win rate vs lower-ranked opponents
        lower_wins = lower_played = 0
        # DF rate
        total_df = total_svpt = 0
        # Bagel sets given
        bagels = total_matches = 0

        for m in self.matches:
            if decay_weight(m.match_date, self.ref) == 0:
                continue
            total_matches += 1
            # Bagels
            if has_bagel_given(m.score):
                bagels += 1
            # DF rate
            if m.df is not None and m.svpt is not None and m.svpt > 0:
                total_df += m.df
                total_svpt += m.svpt

        # Lower-ranked (need opponent rank data)
        # Approximate via matches where they should win (own rank implied from win rate)
        for m in self.matches:
            if decay_weight(m.match_date, self.ref) == 0:
                continue
            if m.opponent_rank is None:
                continue
            if m.opponent_rank > 100:  # rough "lower-ranked" proxy
                lower_played += 1
                if m.won:
                    lower_wins += 1

        consistency_parts = []
        wts = []
        if lower_played >= 5:
            consistency_parts.append(lower_wins / lower_played)
            wts.append(0.40)
        if total_svpt > 0:
            df_rate_inv = 1.0 - (total_df / total_svpt)
            consistency_parts.append(df_rate_inv)
            wts.append(0.30)
        if total_matches > 0:
            bagel_rate_inv = 1.0 - (bagels / total_matches)
            consistency_parts.append(bagel_rate_inv)
            wts.append(0.30)

        if not consistency_parts:
            return None
        total_w = sum(wts)
        return sum(v * w for v, w in zip(consistency_parts, wts)) / total_w

    # ── Net game rating (proxy) ──────────────────────────────────────────

    def net_game_rating_raw(self) -> Optional[float]:
        """
        Proxy until Hawk-Eye data available:
        - Ace-to-DF ratio (serve aggressiveness)
        - Win rate in short matches (< 75 min)
        Flagged as estimated in API.
        """
        ace_vals, short_wins, short_played = [], 0, 0
        for m in self.matches:
            if decay_weight(m.match_date, self.ref) == 0:
                continue
            if m.ace is not None and m.df is not None and (m.ace + m.df) > 0:
                ace_vals.append(m.ace / (m.ace + m.df))
            if m.minutes is not None and m.minutes < 75:
                short_played += 1
                if m.won:
                    short_wins += 1

        parts, wts = [], []
        if ace_vals:
            parts.append(np.mean(ace_vals)); wts.append(0.50)
        if short_played >= 3:
            parts.append(short_wins / short_played); wts.append(0.50)

        if not parts:
            return None
        total_w = sum(wts)
        return sum(v * w for v, w in zip(parts, wts)) / total_w

    # ── Form rating (rolling 10 matches) ────────────────────────────────

    def form_rating_raw(self, n: int = 10) -> Optional[float]:
        """Quality-weighted performance score over the last n matches."""
        recent = [m for m in self.matches
                  if decay_weight(m.match_date, self.ref) > 0][-n:]
        if len(recent) < 3:
            return None
        scores = []
        for m in recent:
            q = quality_weight(m.opponent_rank, m.tourney_level)
            perf = 100.0 * q if m.won else 50.0 * (1 - q)
            scores.append(perf)
        return float(np.mean(scores))

    def momentum(self) -> str:
        """Compare last-5 form vs last-10 form."""
        f10 = self.form_rating_raw(10)
        f5  = self.form_rating_raw(5)
        if f5 is None or f10 is None:
            return 'stable'
        if f5 > f10 + 3:
            return 'rising'
        if f5 < f10 - 3:
            return 'falling'
        return 'stable'

    # ── Big match rating ─────────────────────────────────────────────────

    def big_match_rating_raw(self) -> Optional[float]:
        big = [m for m in self.matches if m.tourney_level in ('G', 'M')]
        if len(big) < MIN_MATCHES_BIG:
            return None
        computer = PlayerRatingComputer(big, self.ref)
        # Use hard surface rating computation logic (surface-agnostic performance)
        total_w = weighted_score = 0.0
        for m in big:
            w = combined_weight(m.match_date, m.opponent_rank, m.tourney_level, self.ref)
            if w == 0:
                continue
            score = 100.0 if m.won else max(0.0, 50.0 - 0.1 * (m.opponent_rank or 300))
            weighted_score += w * score
            total_w += w
        return weighted_score / total_w if total_w > 0 else None

    # ── vs Top 10 rating ────────────────────────────────────────────────

    def vs_top10_rating_raw(self) -> Optional[float]:
        top10 = [m for m in self.matches if m.opponent_rank is not None and m.opponent_rank <= 10]
        if len(top10) < MIN_MATCHES_TOP10:
            return None
        total_w = weighted_score = 0.0
        for m in top10:
            w = combined_weight(m.match_date, m.opponent_rank, m.tourney_level, self.ref)
            if w == 0:
                continue
            score = 100.0 if m.won else 30.0  # losing to top-10 isn't terrible
            weighted_score += w * score
            total_w += w
        return weighted_score / total_w if total_w > 0 else None


# ─────────────────────────────────────────────
# POPULATION NORMALISER
# ─────────────────────────────────────────────

class PopulationNormaliser:
    """
    After computing raw ratings for all active players, normalise each
    dimension to 0–100 (population percentile rank).
    """

    def __init__(self):
        self.populations: dict[str, np.ndarray] = {}

    def fit(self, raw_ratings: dict[str, list[float]]):
        """raw_ratings: {dimension: [raw_score, ...]} for all active players."""
        for dim, scores in raw_ratings.items():
            self.populations[dim] = np.array([s for s in scores if s is not None and not np.isnan(s)])

    def normalise(self, dimension: str, raw_score: Optional[float]) -> Optional[float]:
        if raw_score is None or np.isnan(raw_score):
            return None
        pop = self.populations.get(dimension)
        if pop is None or len(pop) == 0:
            return 50.0
        return normalise_to_population(pop, raw_score)


# ─────────────────────────────────────────────
# MAIN RATINGS PIPELINE
# ─────────────────────────────────────────────

class RatingsPipeline:
    """
    Loads all matches from sa_matches + matches tables,
    computes ratings for every active player,
    writes to player_ratings and player_ratings_history.
    """

    SURFACES = ['Clay', 'Hard', 'Grass', 'Carpet']
    DIMS = [
        'clay_rating', 'hard_rating', 'grass_rating', 'indoor_rating',
        'serve_rating', 'return_rating', 'net_game_rating',
        'pressure_rating', 'consistency_rating', 'form_rating',
        'big_match_rating', 'vs_top10_rating', 'rtt_score',
    ]

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.environ.get(
            'DATABASE_URL',
            'postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway',
        )
        self.reference_date = date.today()

    # ── Data loading ─────────────────────────────────────────────────────

    def _load_matches(self, conn) -> dict[int, list[MatchRecord]]:
        """Load all Sackmann matches and return {player_id: [MatchRecord, ...]}."""
        cutoff = self.reference_date - timedelta(days=MAX_MATCH_AGE_DAYS)
        log.info(f"Loading sa_matches from {cutoff} to {self.reference_date}...")

        sql = """
            SELECT
                winner_id, loser_id,
                tourney_date::date           AS match_date,
                surface, tourney_level,
                winner_rank, loser_rank,
                minutes, best_of, score,
                -- winner serve
                w_ace, w_df, w_svpt, w_1st_in, w_1st_won, w_2nd_won,
                w_sv_gms, w_bp_saved, w_bp_faced,
                -- loser serve (= winner's return)
                l_ace, l_df, l_svpt, l_1st_in, l_1st_won, l_2nd_won,
                l_sv_gms, l_bp_saved, l_bp_faced
            FROM sa_matches
            WHERE tourney_date >= %(cutoff)s
              AND tourney_date <= %(ref)s
              AND score IS NOT NULL
              AND score NOT LIKE '%%W/O%%'
              AND score NOT LIKE '%%RET%%'
        """
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, {'cutoff': cutoff, 'ref': self.reference_date})
            rows = cur.fetchall()

        log.info(f"  Loaded {len(rows):,} matches")

        player_matches: dict[int, list[MatchRecord]] = defaultdict(list)

        for r in rows:
            surface = r['surface'] or 'Hard'
            level = r['tourney_level'] or 'A'
            best_of = r['best_of'] or 3

            # Winner record
            if r['winner_id']:
                player_matches[r['winner_id']].append(MatchRecord(
                    match_date=r['match_date'],
                    surface=surface, tourney_level=level,
                    won=True,
                    opponent_rank=r['loser_rank'],
                    minutes=r['minutes'], best_of=best_of, score=r['score'] or '',
                    ace=r['w_ace'], df=r['w_df'], svpt=r['w_svpt'],
                    first_in=r['w_1st_in'], first_won=r['w_1st_won'],
                    second_won=r['w_2nd_won'], sv_gms=r['w_sv_gms'],
                    bp_saved=r['w_bp_saved'], bp_faced=r['w_bp_faced'],
                    # Opponent serve = loser's serve stats
                    opp_first_in=r['l_1st_in'], opp_first_won=r['l_1st_won'],
                    opp_second_won=r['l_2nd_won'], opp_svpt=r['l_svpt'],
                    opp_bp_faced=r['l_bp_faced'], opp_bp_saved=r['l_bp_saved'],
                ))

            # Loser record
            if r['loser_id']:
                player_matches[r['loser_id']].append(MatchRecord(
                    match_date=r['match_date'],
                    surface=surface, tourney_level=level,
                    won=False,
                    opponent_rank=r['winner_rank'],
                    minutes=r['minutes'], best_of=best_of, score=r['score'] or '',
                    ace=r['l_ace'], df=r['l_df'], svpt=r['l_svpt'],
                    first_in=r['l_1st_in'], first_won=r['l_1st_won'],
                    second_won=r['l_2nd_won'], sv_gms=r['l_sv_gms'],
                    bp_saved=r['l_bp_saved'], bp_faced=r['l_bp_faced'],
                    # Opponent serve = winner's serve stats
                    opp_first_in=r['w_1st_in'], opp_first_won=r['w_1st_won'],
                    opp_second_won=r['w_2nd_won'], opp_svpt=r['w_svpt'],
                    opp_bp_faced=r['w_bp_faced'], opp_bp_saved=r['w_bp_saved'],
                ))

        return player_matches

    def _load_player_ids(self, conn) -> dict[int, int]:
        """
        Map sa_player_id → production player_id by matching on name.
        Returns {sa_player_id: production_player_id}.

        sa_players has name_first + name_last; production players table has
        name (short, e.g. "N. Djokovic") and full_name ("Novak Djokovic").

        Three strategies, applied in priority order (earlier matches win):
          1. Exact full-name match   "Novak Djokovic" == "Novak Djokovic"
          2. Initial + last name     "N. Djokovic" matches name_first="Novak", name_last="Djokovic"
          3. Last-name substring     fallback — p.full_name ILIKE '%Djokovic%'
        """
        log.info("Building sa_player → production player mapping...")

        mapping: dict[int, int] = {}

        # ── Strategy 1: exact full-name match ────────────────────────────
        sql_exact = """
            SELECT sp.player_id AS sa_id, p.id AS prod_id
            FROM sa_players sp
            JOIN players p ON (
                lower(trim(p.full_name)) = lower(trim(sp.name_first || ' ' || sp.name_last))
                OR lower(trim(p.full_name)) = lower(trim(sp.name_last || ' ' || sp.name_first))
                OR lower(trim(p.name))      = lower(trim(sp.name_first || ' ' || sp.name_last))
                OR lower(trim(p.name))      = lower(trim(sp.name_last || ' ' || sp.name_first))
            )
        """
        try:
            with conn.cursor() as cur:
                cur.execute(sql_exact)
                mapping = {row[0]: row[1] for row in cur.fetchall()}
            log.info(f"  Exact-matched {len(mapping):,} players")
        except Exception as e:
            log.warning(f"  Exact match failed: {e}")
            conn.rollback()

        # ── Strategy 2: initial + last name ──────────────────────────────
        # Handles "C. Alcaraz" → name_first="Carlos", name_last="Alcaraz"
        # The production `name` field uses "X. Lastname" format from the API.
        # We compare:
        #   LEFT(sp.name_first, 1)  ==  the letter before the first "." in p.name
        # combined with an exact last-name match.
        sql_initial = """
            SELECT sp.player_id AS sa_id, p.id AS prod_id
            FROM sa_players sp
            JOIN players p ON (
                lower(sp.name_last) = lower(
                    -- extract the part after ". " in short names like "C. Alcaraz"
                    trim(split_part(p.name, '.', 2))
                )
                AND upper(left(sp.name_first, 1)) = upper(
                    -- extract the letter before the "." in "C. Alcaraz"
                    trim(split_part(p.name, '.', 1))
                )
                AND p.name LIKE '%.%'   -- only attempt on abbreviated names
            )
        """
        try:
            with conn.cursor() as cur:
                cur.execute(sql_initial)
                before = len(mapping)
                for row in cur.fetchall():
                    sa_id, prod_id = row[0], row[1]
                    if sa_id not in mapping:
                        mapping[sa_id] = prod_id
            log.info(f"  After initial+lastname match: {len(mapping):,} players mapped "
                     f"(+{len(mapping) - before} new)")
        except Exception as e:
            log.warning(f"  Initial match failed: {e}")
            conn.rollback()

        # ── Strategy 3: last-name substring fallback ─────────────────────
        sql_fuzzy = """
            SELECT sp.player_id AS sa_id, p.id AS prod_id
            FROM sa_players sp
            JOIN players p ON (
                p.full_name ILIKE '%' || sp.name_last || '%'
                OR p.name    ILIKE '%' || sp.name_last || '%'
            )
        """
        try:
            with conn.cursor() as cur:
                cur.execute(sql_fuzzy)
                before = len(mapping)
                for row in cur.fetchall():
                    sa_id, prod_id = row[0], row[1]
                    if sa_id not in mapping:
                        mapping[sa_id] = prod_id
            log.info(f"  After fuzzy match: {len(mapping):,} players mapped total "
                     f"(+{len(mapping) - before} new via fuzzy)")
        except Exception as e:
            log.warning(f"  Fuzzy match failed: {e}")
            conn.rollback()

        return mapping

    # ── Rating computation ───────────────────────────────────────────────

    def _compute_all_raw(self, player_matches: dict) -> dict:
        """Compute raw (un-normalised) ratings for all players."""
        active_cutoff = self.reference_date - timedelta(days=ACTIVE_WINDOW_DAYS)

        all_raw: dict[int, dict] = {}
        for player_id, matches in player_matches.items():
            # Active player check: >= 5 matches in last 18 months
            recent = [m for m in matches if m.match_date >= active_cutoff]
            if len(recent) < MIN_ACTIVE_MATCHES:
                continue

            comp = PlayerRatingComputer(matches, self.reference_date)
            raw = {
                'clay_rating':         comp.surface_rating_raw('Clay'),
                'hard_rating':         comp.surface_rating_raw('Hard'),
                'grass_rating':        comp.surface_rating_raw('Grass'),
                'indoor_rating':       comp.surface_rating_raw('Carpet'),
                'serve_rating':        comp.serve_rating_raw(),
                'return_rating':       comp.return_rating_raw(),
                'net_game_rating':     comp.net_game_rating_raw(),
                'pressure_rating':     comp.pressure_rating_raw(),
                'consistency_rating':  comp.consistency_rating_raw(),
                'form_rating':         comp.form_rating_raw(),
                'big_match_rating':    comp.big_match_rating_raw(),
                'vs_top10_rating':     comp.vs_top10_rating_raw(),
                'momentum':            comp.momentum(),
                'match_count':         len(matches),
            }
            all_raw[player_id] = raw

        log.info(f"Computed raw ratings for {len(all_raw):,} active players")
        return all_raw

    def _normalise_all(self, all_raw: dict) -> dict:
        """Population-normalise all raw ratings to 0–100."""
        norm = PopulationNormaliser()
        dims = [d for d in self.DIMS if d != 'rtt_score']
        pop_data = {d: [r[d] for r in all_raw.values() if r.get(d) is not None] for d in dims}
        norm.fit(pop_data)

        all_normalised: dict[int, dict] = {}
        for player_id, raw in all_raw.items():
            nr = {}
            for dim in dims:
                nr[dim] = norm.normalise(dim, raw.get(dim))
            nr['momentum'] = raw.get('momentum', 'stable')
            nr['match_count'] = raw.get('match_count', 0)

            # RTT Score: 60% surface composite + 40% skill composite
            surface_dims = ['clay_rating', 'hard_rating', 'grass_rating', 'indoor_rating']
            skill_dims   = ['serve_rating', 'return_rating', 'net_game_rating',
                            'pressure_rating', 'consistency_rating']

            surface_vals = [nr[d] for d in surface_dims if nr.get(d) is not None]
            skill_vals   = [nr[d] for d in skill_dims   if nr.get(d) is not None]

            if surface_vals and skill_vals:
                nr['rtt_score'] = round(0.60 * np.mean(surface_vals) + 0.40 * np.mean(skill_vals), 2)
            elif surface_vals:
                nr['rtt_score'] = round(np.mean(surface_vals), 2)
            elif skill_vals:
                nr['rtt_score'] = round(np.mean(skill_vals), 2)
            else:
                nr['rtt_score'] = None

            all_normalised[player_id] = nr

        return all_normalised, norm

    # ── Writing results ──────────────────────────────────────────────────

    @staticmethod
    def _to_python(v):
        """Convert numpy scalars to native Python types for psycopg2 compatibility."""
        if v is None:
            return None
        if isinstance(v, (np.floating, np.float64, np.float32)):
            return float(v)
        if isinstance(v, (np.integer, np.int64, np.int32)):
            return int(v)
        return v

    def _write_ratings(self, conn, all_normalised: dict, player_id_map: dict):
        """Write to player_ratings_history."""
        today = self.reference_date
        log.info(f"Writing {len(all_normalised):,} player ratings to DB...")

        p = self._to_python  # shorthand

        # Deduplicate: multiple sa_ids can map to the same prod_id (fuzzy match).
        # Keep the entry with the highest rtt_score for each production player.
        best: dict[int, dict] = {}
        for sa_id, nr in all_normalised.items():
            prod_id = player_id_map.get(sa_id)
            if not prod_id:
                continue
            existing = best.get(prod_id)
            if existing is None or (nr.get('rtt_score') or 0) > (existing.get('rtt_score') or 0):
                best[prod_id] = nr

        rows_history = []
        for prod_id, nr in best.items():
            rows_history.append((
                prod_id, today,
                p(nr.get('rtt_score')),
                p(nr.get('clay_rating')),
                p(nr.get('hard_rating')),
                p(nr.get('grass_rating')),
                p(nr.get('indoor_rating')),
                p(nr.get('serve_rating')),
                p(nr.get('return_rating')),
                p(nr.get('net_game_rating')),
                p(nr.get('pressure_rating')),
                p(nr.get('consistency_rating')),
                p(nr.get('form_rating')),
                nr.get('momentum', 'stable'),
                p(nr.get('big_match_rating')),
                p(nr.get('vs_top10_rating')),
                int(nr.get('match_count', 0)),
            ))

        if not rows_history:
            log.warning("No mapped player ratings to write (player_id mapping may be empty)")
            return

        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO player_ratings_history (
                    player_id, rated_at,
                    rtt_score, clay_rating, hard_rating, grass_rating, indoor_rating,
                    serve_rating, return_rating, net_game_rating, pressure_rating,
                    consistency_rating, form_rating, momentum,
                    big_match_rating, vs_top10_rating, match_count
                ) VALUES %s
                ON CONFLICT (player_id, rated_at) DO UPDATE SET
                    rtt_score          = EXCLUDED.rtt_score,
                    clay_rating        = EXCLUDED.clay_rating,
                    hard_rating        = EXCLUDED.hard_rating,
                    grass_rating       = EXCLUDED.grass_rating,
                    indoor_rating      = EXCLUDED.indoor_rating,
                    serve_rating       = EXCLUDED.serve_rating,
                    return_rating      = EXCLUDED.return_rating,
                    net_game_rating    = EXCLUDED.net_game_rating,
                    pressure_rating    = EXCLUDED.pressure_rating,
                    consistency_rating = EXCLUDED.consistency_rating,
                    form_rating        = EXCLUDED.form_rating,
                    momentum           = EXCLUDED.momentum,
                    big_match_rating   = EXCLUDED.big_match_rating,
                    vs_top10_rating    = EXCLUDED.vs_top10_rating,
                    match_count        = EXCLUDED.match_count
            """, rows_history, page_size=200)

        conn.commit()
        log.info(f"  Wrote {len(rows_history)} rows to player_ratings_history")

    def _write_calibration(self, conn, norm: PopulationNormaliser):
        """Store population percentile checkpoints in rating_calibration."""
        today = self.reference_date
        rows = []
        for dim, pop in norm.populations.items():
            if len(pop) == 0:
                continue
            rows.append((
                dim, today,
                float(np.percentile(pop, 10)),
                float(np.percentile(pop, 25)),
                float(np.percentile(pop, 50)),
                float(np.percentile(pop, 75)),
                float(np.percentile(pop, 90)),
                int(len(pop)),
            ))

        if not rows:
            return

        try:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO rating_calibration
                        (dimension, calibrated_at, p10, p25, p50, p75, p90, player_count)
                    VALUES %s
                    ON CONFLICT (dimension, calibrated_at) DO UPDATE SET
                        p10 = EXCLUDED.p10, p25 = EXCLUDED.p25,
                        p50 = EXCLUDED.p50, p75 = EXCLUDED.p75,
                        p90 = EXCLUDED.p90, player_count = EXCLUDED.player_count
                """, rows)
            conn.commit()
            log.info(f"  Wrote {len(rows)} calibration checkpoints")
        except Exception as e:
            log.warning(f"  Could not write calibration (table may not exist yet): {e}")
            conn.rollback()

    def _write_current_ratings(self, conn, all_normalised: dict, player_id_map: dict):
        """
        Upsert current ratings into player_ratings (the live-facing table).
        Maps RTT dimension names to the player_ratings column names.
        """
        today = self.reference_date
        p = self._to_python  # convert numpy types
        # Deduplicate: keep highest rtt_score per production player_id
        best_current: dict[int, dict] = {}
        for sa_id, nr in all_normalised.items():
            prod_id = player_id_map.get(sa_id)
            if not prod_id:
                continue
            existing = best_current.get(prod_id)
            if existing is None or (nr.get('rtt_score') or 0) > (existing.get('rtt_score') or 0):
                best_current[prod_id] = nr

        rows = []
        for prod_id, nr in best_current.items():
            rows.append((
                prod_id,
                p(nr.get('rtt_score')),
                p(nr.get('clay_rating')),
                p(nr.get('hard_rating')),
                p(nr.get('grass_rating')),
                p(nr.get('indoor_rating')),
                p(nr.get('serve_rating')),
                p(nr.get('return_rating')),
                p(nr.get('net_game_rating')),
                p(nr.get('pressure_rating')),
                p(nr.get('consistency_rating')),
                p(nr.get('form_rating')),
                nr.get('momentum', 'stable'),
                p(nr.get('big_match_rating')),
                p(nr.get('vs_top10_rating')),
                today,
            ))

        if not rows:
            log.warning("  No current ratings to write to player_ratings")
            return

        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO player_ratings (
                    player_id,
                    rtt_score, clay_rating, hard_rating, grass_rating, indoor_rating,
                    serve_rating, return_rating, net_game_rating, pressure_rating,
                    consistency_score, form_score, momentum,
                    big_match_rating, vs_top10_rating, calculated_at
                ) VALUES %s
                ON CONFLICT (player_id) DO UPDATE SET
                    rtt_score          = EXCLUDED.rtt_score,
                    clay_rating        = EXCLUDED.clay_rating,
                    hard_rating        = EXCLUDED.hard_rating,
                    grass_rating       = EXCLUDED.grass_rating,
                    indoor_rating      = EXCLUDED.indoor_rating,
                    serve_rating       = EXCLUDED.serve_rating,
                    return_rating      = EXCLUDED.return_rating,
                    net_game_rating    = EXCLUDED.net_game_rating,
                    pressure_rating    = EXCLUDED.pressure_rating,
                    consistency_score  = EXCLUDED.consistency_score,
                    form_score         = EXCLUDED.form_score,
                    momentum           = EXCLUDED.momentum,
                    big_match_rating   = EXCLUDED.big_match_rating,
                    vs_top10_rating    = EXCLUDED.vs_top10_rating,
                    calculated_at      = EXCLUDED.calculated_at
            """, rows, page_size=200)
        conn.commit()
        log.info(f"  Wrote {len(rows)} rows to player_ratings (current)")

    # ── Supplemental ratings from production match history ───────────────

    def _supplement_from_production(self, conn):
        """
        For production players with NO Sackmann-based rating, compute basic
        RTT scores from their match history in the production matches table.

        This covers Challenger/ITF players and newer players not in Sackmann data.
        Scores are capped at 65 (below typical Sackmann-rated players) since we
        have no serve/return stats and the population is less well-defined.

        Only writes to rows where rtt_score IS NULL — never overwrites Sackmann data.
        """
        log.info("Supplementing ratings from production match history...")

        # Find production players without any RTT score yet
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT p.id, p.name, p.ranking
                FROM players p
                LEFT JOIN player_ratings pr ON pr.player_id = p.id
                WHERE pr.player_id IS NULL OR pr.rtt_score IS NULL
            """)
            unrated = cur.fetchall()

        if not unrated:
            log.info("  All players already have RTT scores")
            return

        unrated_ids = [r['id'] for r in unrated]
        log.info(f"  {len(unrated_ids)} players without RTT score — loading production matches...")

        cutoff = self.reference_date - timedelta(days=MAX_MATCH_AGE_DAYS)

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    m.event_date,
                    m.first_player_id,
                    m.second_player_id,
                    m.winner,
                    s.name AS surface,
                    et.tour_category,
                    p1.ranking AS p1_rank,
                    p2.ranking AS p2_rank
                FROM matches m
                LEFT JOIN tournaments t   ON t.id  = m.tournament_id
                LEFT JOIN surfaces s      ON s.id  = t.surface_id
                LEFT JOIN event_types et  ON et.id = m.event_type_id
                JOIN players p1 ON p1.id = m.first_player_id
                JOIN players p2 ON p2.id = m.second_player_id
                WHERE m.event_date >= %s
                  AND m.event_status = 'Finished'
                  AND m.winner IS NOT NULL
                  AND (
                    m.first_player_id  = ANY(%s)
                    OR m.second_player_id = ANY(%s)
                  )
                ORDER BY m.event_date
            """, (cutoff, unrated_ids, unrated_ids))
            prod_rows = cur.fetchall()

        log.info(f"  Loaded {len(prod_rows)} production matches")

        if not prod_rows:
            log.info("  No production match history — skipping supplemental ratings")
            return

        unrated_set = set(unrated_ids)
        player_data: dict[int, list[dict]] = defaultdict(list)

        for r in prod_rows:
            fp, sp = r['first_player_id'], r['second_player_id']
            won_fp  = r['winner'] == 'First Player'
            surface = r['surface'] or 'Hard'
            tour    = r['tour_category'] or ''
            mdate   = r['event_date']

            if fp in unrated_set:
                player_data[fp].append({
                    'date': mdate, 'surface': surface, 'tour': tour,
                    'won': won_fp, 'opp_rank': r['p2_rank'],
                })
            if sp in unrated_set:
                player_data[sp].append({
                    'date': mdate, 'surface': surface, 'tour': tour,
                    'won': not won_fp, 'opp_rank': r['p1_rank'],
                })

        today = self.reference_date
        rows_written = 0

        for player_id in unrated_ids:
            matches = player_data.get(player_id, [])
            if len(matches) < 3:
                continue

            matches.sort(key=lambda m: m['date'] or date.min)

            def _weight(m):
                days_ago = (today - (m['date'] or today)).days
                return np.exp(-days_ago * np.log(2) / HALF_LIFE_DAYS)

            weights    = [_weight(m) for m in matches]
            total_w    = sum(weights) or 1.0
            win_rate   = sum(w for m, w in zip(matches, weights) if m['won']) / total_w

            def _surface_rate(surf):
                ms = [(m, w) for m, w in zip(matches, weights)
                      if (m['surface'] or '').lower().startswith(surf.lower())]
                if len(ms) < 2:
                    return None
                wins  = sum(w for m, w in ms if m['won'])
                total = sum(w for _, w in ms)
                return wins / total if total else None

            clay_rate  = _surface_rate('Clay')
            hard_rate  = _surface_rate('Hard')
            grass_rate = _surface_rate('Grass')

            recent = matches[-10:]
            form_parts = []
            for m in recent:
                rank    = m.get('opp_rank') or 200
                quality = max(0.5, min(2.0, 100.0 / rank))
                form_parts.append(quality if m['won'] else 0.0)
            form_raw = (sum(form_parts) / (len(form_parts) * 2.0)) if form_parts else 0.0

            if len(matches) >= 10:
                r5  = sum(1 for m in matches[-5:]    if m['won']) / 5.0
                p5  = sum(1 for m in matches[-10:-5] if m['won']) / 5.0
                momentum = 'rising' if r5 - p5 > 0.2 else ('falling' if p5 - r5 > 0.2 else 'stable')
            elif len(matches) >= 5:
                r5  = sum(1 for m in matches[-5:] if m['won']) / 5.0
                momentum = 'rising' if r5 > 0.6 else ('falling' if r5 < 0.3 else 'stable')
            else:
                momentum = 'stable'

            big_ms   = [m for m in matches if m['tour'] in ('Grand Slam', 'ATP Masters 1000', 'WTA Premier')]
            big_rate = (sum(1 for m in big_ms if m['won']) / len(big_ms)) if big_ms else None

            # Conservative composite — capped at 65 without serve/return data
            rtt = min(65.0, max(5.0, win_rate * 50 + form_raw * 30 + len(matches) * 0.2))

            def _to_score(rate):
                return round(min(65.0, max(5.0, rate * 65.0)), 2) if rate is not None else None

            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO player_ratings (
                            player_id,
                            rtt_score, clay_rating, hard_rating, grass_rating, indoor_rating,
                            serve_rating, return_rating, net_game_rating, pressure_rating,
                            consistency_score, form_score, momentum,
                            big_match_rating, vs_top10_rating, calculated_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (player_id) DO UPDATE SET
                            rtt_score     = EXCLUDED.rtt_score,
                            clay_rating   = EXCLUDED.clay_rating,
                            hard_rating   = EXCLUDED.hard_rating,
                            grass_rating  = EXCLUDED.grass_rating,
                            form_score    = EXCLUDED.form_score,
                            momentum      = EXCLUDED.momentum,
                            calculated_at = EXCLUDED.calculated_at
                        WHERE player_ratings.rtt_score IS NULL
                    """, (
                        player_id,
                        round(rtt, 2),
                        _to_score(clay_rate),
                        _to_score(hard_rate),
                        _to_score(grass_rate),
                        None, None, None, None, None, None,
                        round(form_raw * 100, 2),
                        momentum,
                        _to_score(big_rate),
                        None,
                        today,
                    ))
                rows_written += 1
            except Exception as e:
                log.debug(f"  Supplemental rating failed for player {player_id}: {e}")
                conn.rollback()
                continue

        conn.commit()
        log.info(f"  Supplemental ratings written for {rows_written} additional players")

    # ── Entry point ──────────────────────────────────────────────────────

    def run(self):
        log.info("=== RTT Rating Pipeline ===")
        conn = psycopg2.connect(self.db_url)

        try:
            player_matches = self._load_matches(conn)
            player_id_map = self._load_player_ids(conn)

            log.info("Computing raw ratings...")
            all_raw = self._compute_all_raw(player_matches)

            log.info("Normalising to population...")
            all_normalised, norm = self._normalise_all(all_raw)

            self._write_ratings(conn, all_normalised, player_id_map)
            self._write_current_ratings(conn, all_normalised, player_id_map)
            self._write_calibration(conn, norm)

            # Supplement: basic ratings for players not in Sackmann data
            self._supplement_from_production(conn)

            log.info("✅ Rating pipeline complete")
        finally:
            conn.close()

    def run_in_memory(self) -> dict[int, dict]:
        """
        Run pipeline and return normalised ratings dict without writing to DB.
        Useful for testing or for seeding the feature builder.
        """
        conn = psycopg2.connect(self.db_url)
        try:
            player_matches = self._load_matches(conn)
            all_raw = self._compute_all_raw(player_matches)
            all_normalised, norm = self._normalise_all(all_raw)
            return all_normalised
        finally:
            conn.close()


# ─────────────────────────────────────────────
# TIER HELPER
# ─────────────────────────────────────────────

def rating_tier(score: Optional[float]) -> dict:
    if score is None:
        return {"label": "Unknown", "colour": "#888780"}
    for threshold, label, colour in RATING_TIERS:
        if score >= threshold:
            return {"label": label, "colour": colour}
    return {"label": "Poor", "colour": "#E24B4A"}


# ─────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="ratethat.tennis rating pipeline")
    parser.add_argument('--dry-run', action='store_true',
                        help='Compute ratings but do not write to DB')
    args = parser.parse_args()

    pipeline = RatingsPipeline()

    if args.dry_run:
        results = pipeline.run_in_memory()
        log.info(f"Dry run complete — {len(results)} active players rated")
        # Show a sample
        sample = list(results.items())[:5]
        for pid, r in sample:
            log.info(f"  Player {pid}: RTT={r.get('rtt_score')}, "
                     f"Clay={r.get('clay_rating')}, Serve={r.get('serve_rating')}, "
                     f"Momentum={r.get('momentum')}")
    else:
        pipeline.run()


if __name__ == '__main__':
    main()
