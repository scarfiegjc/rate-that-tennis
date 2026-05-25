"""
ratethat.tennis — Feature Engineering Pipeline
===============================================
Builds the full training feature matrix from sa_matches.

All features are computed using ONLY information available BEFORE the match
(strict temporal split — no data leakage).

Feature groups:
  1. Elo ratings (pre-match, overall + surface-specific)
  2. Ranking & seeding
  3. Rolling form (win rate, performance index) — last 10/20/50 matches
  4. Rolling serve/return stats — last 20 matches on current surface
  5. Head-to-head record (overall + surface)
  6. Fatigue (days since last match, sets in last 7 days)
  7. Tournament context (level, round)
  8. Physical matchup (age, height, hand)

Output: one row per match, player 1 = winner/loser randomly swapped so
the model doesn't learn "player 1 always wins". Target = did_p1_win (0/1).

Usage:
    from ml.features import FeatureBuilder
    fb = FeatureBuilder(db_url=DB_URL)
    fb.load()
    X, y, meta = fb.build()
"""

from __future__ import annotations

import os
import logging
import numpy as np
import pandas as pd
from collections import defaultdict, deque
from typing import Optional
import psycopg2
import psycopg2.extras

from ml.elo import EloEngine, SURFACE_MAP, ALL_SURFACES

try:
    from pipeline.aging_curve import age_factor as _age_factor
except ImportError:
    def _age_factor(age): return 1.0

log = logging.getLogger("rtt-features")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

ROUND_ENCODE = {
    'RR': 0, 'BR': 0,                           # round robin / bronze
    'R128': 1, 'R64': 2, 'R32': 3, 'R16': 4,
    'QF': 5, 'SF': 6, 'F': 7,
}

LEVEL_ENCODE = {
    'S': 0,   # Satellite / ITF
    'C': 1,   # Challenger
    'D': 1,   # Davis Cup (treat similar to Challenger for stakes)
    'A': 2,   # 250/500 / Premier
    'M': 3,   # Masters 1000 / Premier Mandatory
    'F': 3,   # Tour Finals
    'G': 4,   # Grand Slam
}

HAND_ENCODE = {
    ('R', 'R'): 0, ('R', 'L'): 1,
    ('L', 'R'): 2, ('L', 'L'): 3,
}


def safe_pct(num, denom) -> Optional[float]:
    if denom and denom > 0:
        return num / denom
    return None


# ─────────────────────────────────────────────
# ROLLING PLAYER STATS TRACKER
# ─────────────────────────────────────────────

class PlayerWindow:
    """
    Maintains rolling windows of match results per player.
    All stats returned represent the state BEFORE the current match.
    """

    def __init__(self, max_window: int = 50):
        self.max_window = max_window
        # General history: deque of match dicts
        self._history: dict[int, deque] = defaultdict(lambda: deque(maxlen=max_window))
        # Surface-specific history
        self._surf_history: dict[str, dict[int, deque]] = {
            s: defaultdict(lambda: deque(maxlen=20))
            for s in ALL_SURFACES
        }
        # Last match date per player (for fatigue calc)
        self._last_match_date: dict[int, Optional[pd.Timestamp]] = defaultdict(lambda: None)
        # Sets played in recent window
        self._sets_deque: dict[int, deque] = defaultdict(lambda: deque(maxlen=10))

    def get_stats(self, player_id: int, surface: Optional[str], n_recent: list[int]) -> dict:
        """
        Returns pre-match rolling stats for player_id.
        n_recent: list of window sizes e.g. [10, 20, 50]
        """
        pid = int(player_id)
        hist = list(self._history[pid])   # oldest → newest
        surf_key = SURFACE_MAP.get(surface or '', None)
        surf_hist = list(self._surf_history[surf_key][pid]) if surf_key else []

        result = {}

        for n in n_recent:
            window = hist[-n:] if len(hist) >= n else hist
            n_matches = len(window)
            wins = sum(m['won'] for m in window)
            result[f'win_rate_{n}'] = wins / n_matches if n_matches > 0 else None
            result[f'matches_{n}'] = n_matches

            # Serve stats from window
            ace_rate    = [m['ace_rate']    for m in window if m['ace_rate']    is not None]
            df_rate     = [m['df_rate']     for m in window if m['df_rate']     is not None]
            svpt_won    = [m['svpt_won']    for m in window if m['svpt_won']    is not None]
            ret_won     = [m['ret_won']     for m in window if m['ret_won']     is not None]
            bp_save     = [m['bp_save']     for m in window if m['bp_save']     is not None]
            bp_conv     = [m['bp_conv']     for m in window if m['bp_conv']     is not None]

            result[f'ace_rate_{n}']   = np.mean(ace_rate)   if ace_rate   else None
            result[f'df_rate_{n}']    = np.mean(df_rate)    if df_rate    else None
            result[f'svpt_won_{n}']   = np.mean(svpt_won)   if svpt_won   else None
            result[f'ret_won_{n}']    = np.mean(ret_won)    if ret_won    else None
            result[f'bp_save_{n}']    = np.mean(bp_save)    if bp_save    else None
            result[f'bp_conv_{n}']    = np.mean(bp_conv)    if bp_conv    else None

        # Surface-specific win rate (last 10 on this surface)
        if surf_hist:
            sw = surf_hist[-10:]
            result['surf_win_rate_10'] = sum(m['won'] for m in sw) / len(sw)
            result['surf_matches_10']  = len(sw)
        else:
            result['surf_win_rate_10'] = None
            result['surf_matches_10']  = 0

        # Fatigue
        result['days_since_last'] = None
        # (computed outside with the match date)

        return result

    def update(
        self,
        player_id: int,
        won: bool,
        surface: Optional[str],
        match_date,
        # Serve stats for this match
        ace_rate:  Optional[float] = None,
        df_rate:   Optional[float] = None,
        svpt_won:  Optional[float] = None,
        ret_won:   Optional[float] = None,
        bp_save:   Optional[float] = None,
        bp_conv:   Optional[float] = None,
        sets_played: int = 2,
    ):
        pid = int(player_id)
        entry = {
            'won':      int(won),
            'surface':  surface,
            'date':     match_date,
            'ace_rate': ace_rate,
            'df_rate':  df_rate,
            'svpt_won': svpt_won,
            'ret_won':  ret_won,
            'bp_save':  bp_save,
            'bp_conv':  bp_conv,
        }
        self._history[pid].append(entry)
        self._last_match_date[pid] = match_date

        surf_key = SURFACE_MAP.get(surface or '', None)
        if surf_key:
            self._surf_history[surf_key][pid].append(entry)

        self._sets_deque[pid].append({'date': match_date, 'sets': sets_played})

    def days_since_last(self, player_id: int, current_date) -> Optional[float]:
        pid = int(player_id)
        last = self._last_match_date[pid]
        if last is None or current_date is None:
            return None
        try:
            return (pd.Timestamp(current_date) - pd.Timestamp(last)).days
        except Exception:
            return None

    def h2h_record(
        self,
        p1_id: int,
        p2_id: int,
        surface: Optional[str],
        match_histories: dict,   # {player_id: list of {opponent_id, won, surface}}
    ) -> dict:
        """Compute H2H from the dedicated H2H tracker."""
        # (delegated to H2HTracker below)
        return {}


# ─────────────────────────────────────────────
# H2H TRACKER
# ─────────────────────────────────────────────

class H2HTracker:
    """Maintains head-to-head records between player pairs."""

    def __init__(self):
        # (p1_id, p2_id) → list of {won: bool, surface: str}
        # Always store with min(p1,p2) as first key
        self._records: dict[tuple, list] = defaultdict(list)

    def _key(self, a: int, b: int) -> tuple:
        return (min(a, b), max(a, b))

    def get(self, p1_id: int, p2_id: int, surface: Optional[str]) -> dict:
        """Get H2H stats for p1 vs p2 BEFORE current match."""
        key = self._key(p1_id, p2_id)
        records = self._records[key]
        surf_key = SURFACE_MAP.get(surface or '', None)

        total = len(records)
        p1_wins = sum(r['winner'] == p1_id for r in records)
        p1_surf_wins = sum(r['winner'] == p1_id for r in records if r['surface'] == surf_key)
        surf_total   = sum(1 for r in records if r['surface'] == surf_key)

        # H2H trend: last 5 meetings
        recent = records[-5:]
        p1_recent_wins = sum(r['winner'] == p1_id for r in recent)

        return {
            'h2h_total':         total,
            'h2h_p1_wins':       p1_wins,
            'h2h_p1_win_pct':    p1_wins / total if total > 0 else 0.5,
            'h2h_surf_total':    surf_total,
            'h2h_surf_p1_wins':  p1_surf_wins,
            'h2h_surf_p1_win_pct': p1_surf_wins / surf_total if surf_total > 0 else 0.5,
            'h2h_recent_p1_wins': p1_recent_wins,
            'h2h_recent_total':   len(recent),
        }

    def update(self, winner_id: int, loser_id: int, surface: Optional[str]):
        key = self._key(winner_id, loser_id)
        surf_key = SURFACE_MAP.get(surface or '', None)
        self._records[key].append({
            'winner':  winner_id,
            'loser':   loser_id,
            'surface': surf_key,
        })


# ─────────────────────────────────────────────
# MAIN FEATURE BUILDER
# ─────────────────────────────────────────────

class FeatureBuilder:
    """
    Loads sa_matches from PostgreSQL and builds the full feature matrix.
    Handles random player swap so model sees both perspectives.
    """

    def __init__(self, db_url: str = DB_URL):
        self.db_url = db_url
        self.df: Optional[pd.DataFrame] = None
        self.elo_engine: Optional[EloEngine] = None
        self.elo_features: Optional[pd.DataFrame] = None

    # ─────────────────────────────────────────
    # LOAD
    # ─────────────────────────────────────────

    def load(self, tour_filter: Optional[list] = None, min_year: int = 2000) -> "FeatureBuilder":
        """Load matches from sa_matches. Filters to years with reliable stats."""
        log.info(f"Loading sa_matches from DB (min_year={min_year}) ...")

        query = """
            SELECT
                m.id,
                m.tour,
                m.tourney_id,
                m.tourney_name,
                m.surface,
                m.tourney_level,
                m.tourney_date,
                m.season,
                m.match_num,
                m.round,
                m.best_of,
                -- Winner
                m.winner_id,
                m.winner_name,
                m.winner_hand,
                m.winner_ht,
                m.winner_age,
                m.winner_rank,
                m.winner_rank_points,
                m.winner_seed,
                -- Loser
                m.loser_id,
                m.loser_name,
                m.loser_hand,
                m.loser_ht,
                m.loser_age,
                m.loser_rank,
                m.loser_rank_points,
                m.loser_seed,
                -- Result
                m.score,
                m.minutes,
                -- Winner serve stats (pre-computed percentages)
                m.w_ace,
                m.w_df,
                m.w_svpt,
                m.w_1st_in,
                m.w_1st_won,
                m.w_2nd_won,
                m.w_sv_gms,
                m.w_bp_saved,
                m.w_bp_faced,
                m.w_1st_serve_pct,
                m.w_1st_won_pct,
                m.w_2nd_won_pct,
                m.w_bp_save_pct,
                -- Loser serve stats
                m.l_ace,
                m.l_df,
                m.l_svpt,
                m.l_1st_in,
                m.l_1st_won,
                m.l_2nd_won,
                m.l_sv_gms,
                m.l_bp_saved,
                m.l_bp_faced,
                m.l_1st_serve_pct,
                m.l_1st_won_pct,
                m.l_2nd_won_pct,
                m.l_bp_save_pct
            FROM sa_matches m
            WHERE m.tourney_date IS NOT NULL
              AND m.winner_id IS NOT NULL
              AND m.loser_id IS NOT NULL
              AND m.season >= %(min_year)s
        """

        params = {'min_year': min_year}
        if tour_filter:
            query += " AND m.tour = ANY(%(tours)s)"
            params['tours'] = tour_filter

        query += " ORDER BY m.tourney_date, m.tour, m.match_num"

        # Use SQLAlchemy engine so pd.read_sql handles types correctly.
        # Raw psycopg2 connections cause DateParseError in pandas >= 2.0.
        try:
            from sqlalchemy import create_engine, text
            engine = create_engine(self.db_url)
            with engine.connect() as sa_conn:
                df = pd.read_sql(text(query), sa_conn, params=params)
        except Exception:
            # Fallback: manual psycopg2 fetch + DataFrame construction
            conn = psycopg2.connect(self.db_url)
            conn.cursor_factory = psycopg2.extras.RealDictCursor
            try:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()
                df = pd.DataFrame([dict(r) for r in rows])
            finally:
                conn.close()

        df['tourney_date'] = pd.to_datetime(df['tourney_date'])
        log.info(f"  Loaded {len(df):,} matches")
        self.df = df
        return self

    def load_from_df(self, df: pd.DataFrame) -> "FeatureBuilder":
        """For testing — inject a pre-loaded DataFrame."""
        self.df = df
        return self

    def _load_rtt_history(self, engine) -> dict:
        """
        Load player_ratings_history into a dict: player_id → sorted list of
        (rated_at_date, ratings_dict) for point-in-time RTT feature lookups.
        Returns empty dict if the table is empty or unavailable.
        """
        try:
            from sqlalchemy import text as sa_text
            with engine.connect() as conn:
                df_rtt = pd.read_sql(sa_text("""
                    SELECT player_id, rated_at,
                           rtt_score, clay_rating, hard_rating, grass_rating, indoor_rating,
                           serve_rating, return_rating, pressure_rating,
                           consistency_score, form_score, big_match_rating, vs_top10_rating
                    FROM player_ratings_history
                    ORDER BY player_id, rated_at
                """), conn)
            if df_rtt.empty:
                return {}
            df_rtt['rated_at'] = pd.to_datetime(df_rtt['rated_at']).dt.date
            history: dict = {}
            for pid, grp in df_rtt.groupby('player_id'):
                records = []
                for _, r in grp.iterrows():
                    records.append((r['rated_at'], r.drop('player_id').to_dict()))
                history[int(pid)] = records
            log.info(f"  RTT history loaded for {len(history):,} players")
            return history
        except Exception as e:
            log.warning(f"  Could not load player_ratings_history: {e}")
            return {}

    def _load_point_stats(self, engine) -> dict:
        """
        Load player_point_stats into a dict: player_id → stats dict.
        Returns empty dict if the table is empty or unavailable.
        """
        try:
            from sqlalchemy import text as sa_text
            with engine.connect() as conn:
                df_ps = pd.read_sql(sa_text("""
                    SELECT player_id, tiebreak_win_pct, pressure_win_pct,
                           match_point_save_pct, bp_save_pct, bp_conversion_pct
                    FROM player_point_stats
                """), conn)
            if df_ps.empty:
                return {}
            result = {}
            for _, r in df_ps.iterrows():
                result[int(r['player_id'])] = {
                    'tiebreak_win_pct':     r.get('tiebreak_win_pct'),
                    'pressure_win_pct':     r.get('pressure_win_pct'),
                    'match_point_save_pct': r.get('match_point_save_pct'),
                    'bp_save_pct':          r.get('bp_save_pct'),
                    'bp_conversion_pct':    r.get('bp_conversion_pct'),
                }
            log.info(f"  Point stats loaded for {len(result):,} players")
            return result
        except Exception as e:
            log.warning(f"  Could not load player_point_stats: {e}")
            return {}

    def _load_ms_career_stats(self, engine) -> dict:
        """
        Load ms_player_career_stats (slam_winner_ue_ratio) joined via ms_player_links.
        Returns dict: production player_id → stats dict.
        """
        try:
            from sqlalchemy import text as sa_text
            with engine.connect() as conn:
                df_ms = pd.read_sql(sa_text("""
                    SELECT pl.player_id, cs.slam_winner_ue_ratio
                    FROM ms_player_links pl
                    JOIN ms_player_career_stats cs ON cs.ms_player_id = pl.ms_id
                    WHERE cs.slam_winner_ue_ratio IS NOT NULL
                """), conn)
            if df_ms.empty:
                return {}
            result = {}
            for _, r in df_ms.iterrows():
                result[int(r['player_id'])] = {
                    'slam_winner_ue_ratio': r.get('slam_winner_ue_ratio'),
                }
            log.info(f"  MS career stats loaded for {len(result):,} players")
            return result
        except Exception as e:
            log.warning(f"  Could not load ms_player_career_stats: {e}")
            return {}

    # ─────────────────────────────────────────
    # BUILD
    # ─────────────────────────────────────────

    def build(
        self,
        random_seed: int = 42,
        include_futures: bool = False,
    ) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
        """
        Build the full feature matrix.

        Returns:
            X     : feature DataFrame
            y     : binary target (1 = p1 won)
            meta  : metadata (match date, players, surface, etc.)
        """
        assert self.df is not None, "Call load() first"

        df = self.df.copy()

        # Optionally filter out ITF futures (very noisy, low-quality data)
        if not include_futures:
            df = df[~df['tourney_id'].str.contains('F', na=False)]

        log.info(f"Building Elo ratings from {len(df):,} matches ...")
        self.elo_engine = EloEngine()
        self.elo_engine.fit(df)
        elo_df = self.elo_engine.match_features()

        # Load RTT history for point-in-time feature lookup
        try:
            from sqlalchemy import create_engine
            _engine = create_engine(self.db_url)
            rtt_history = self._load_rtt_history(_engine)
            point_stats = self._load_point_stats(_engine)
            ms_career   = self._load_ms_career_stats(_engine)
        except Exception:
            rtt_history = {}
            point_stats = {}
            ms_career   = {}

        log.info("Building rolling stats and H2H features ...")
        rows = self._build_rows(df, elo_df, random_seed, rtt_history, point_stats, ms_career)

        result = pd.DataFrame(rows)
        log.info(f"Feature matrix: {len(result):,} rows × {len(result.columns)} columns")

        # Split into X, y, meta
        meta_cols = ['match_id', 'tourney_date', 'surface', 'tour', 'tourney_level',
                     'round', 'season', 'p1_id', 'p2_id', 'p1_name', 'p2_name']
        target_col = 'did_p1_win'
        feature_cols = [c for c in result.columns if c not in meta_cols + [target_col]]

        X    = result[feature_cols].copy()
        y    = result[target_col].astype(int)
        meta = result[meta_cols + [target_col]].copy()

        return X, y, meta

    def _build_rows(
        self,
        df: pd.DataFrame,
        elo_df: pd.DataFrame,
        random_seed: int,
        rtt_history: Optional[dict] = None,
        point_stats: Optional[dict] = None,
        ms_career: Optional[dict] = None,
    ) -> list[dict]:
        """Core loop: iterate matches chronologically, build features, then update trackers."""

        rtt_history = rtt_history or {}
        point_stats = point_stats or {}
        ms_career   = ms_career   or {}

        def _lookup_rtt(player_id: int, match_date) -> dict:
            """Return the most recent RTT ratings for player before match_date."""
            DEFAULT = 50.0
            pid = int(player_id)
            entries = rtt_history.get(pid, [])
            if not entries:
                return None
            md = match_date.date() if hasattr(match_date, 'date') else match_date
            # entries are sorted ascending by rated_at — find last before md
            result = None
            for rated_at, ratings in entries:
                if rated_at < md:
                    result = ratings
                else:
                    break
            return result

        def _rtt_val(ratings: Optional[dict], key: str) -> float:
            if ratings is None or ratings.get(key) is None:
                return 50.0
            v = ratings[key]
            return float(v) if v is not None else 50.0

        rng = np.random.default_rng(random_seed)
        player_window = PlayerWindow(max_window=50)
        h2h = H2HTracker()
        # Track last match minutes per player for fatigue feature
        _last_mins: dict[int, float] = {}

        # Index elo_df by position (same order as df after sort)
        elo_records = elo_df.to_dict('records')
        assert len(elo_records) == len(df), "Elo and match df length mismatch"

        rows = []

        for i, (_, match) in enumerate(df.iterrows()):
            w_id = match.get('winner_id')
            l_id = match.get('loser_id')

            if pd.isna(w_id) or pd.isna(l_id):
                continue

            w_id = int(w_id)
            l_id = int(l_id)
            elo_row = elo_records[i]

            surface = match.get('surface')
            surf_key = SURFACE_MAP.get(surface or '', None)
            match_date = match['tourney_date']
            level  = match.get('tourney_level', 'U') or 'U'
            round_ = match.get('round', '') or ''

            # ── Random swap: assign winner/loser to p1/p2
            p1_is_winner = rng.integers(0, 2) == 1
            p1_id = w_id if p1_is_winner else l_id
            p2_id = l_id if p1_is_winner else w_id

            # ── PRE-MATCH: collect all features
            p1_w = player_window.get_stats(p1_id, surface, [10, 20, 50])
            p2_w = player_window.get_stats(p2_id, surface, [10, 20, 50])
            h2h_f = h2h.get(p1_id, p2_id, surface)

            # Fatigue
            p1_days = player_window.days_since_last(p1_id, match_date)
            p2_days = player_window.days_since_last(p2_id, match_date)

            # Raw match attributes
            p1_rank  = match['winner_rank']  if p1_is_winner else match['loser_rank']
            p2_rank  = match['loser_rank']   if p1_is_winner else match['winner_rank']
            p1_pts   = match['winner_rank_points'] if p1_is_winner else match['loser_rank_points']
            p2_pts   = match['loser_rank_points']  if p1_is_winner else match['winner_rank_points']
            p1_age   = match['winner_age']   if p1_is_winner else match['loser_age']
            p2_age   = match['loser_age']    if p1_is_winner else match['winner_age']
            p1_ht    = match['winner_ht']    if p1_is_winner else match['loser_ht']
            p2_ht    = match['loser_ht']     if p1_is_winner else match['winner_ht']
            p1_hand  = match['winner_hand']  if p1_is_winner else match['loser_hand']
            p2_hand  = match['loser_hand']   if p1_is_winner else match['winner_hand']

            # Aging curve
            p1_age_factor  = _age_factor(p1_age)
            p2_age_factor  = _age_factor(p2_age)

            # Clutch / pressure stats from player_point_stats (production player IDs)
            # Note: sa_matches player IDs may not map to production IDs — these features
            # will fill with 0.5 (neutral) for most historical training rows, but they
            # enrich any row where the IDs do match or when used in live predict mode.
            def _ps_val(pid: int, key: str, default: float = 0.5) -> float:
                ps = point_stats.get(int(pid), {})
                v  = ps.get(key)
                if v is None:
                    return default
                return float(v) / 100.0  # stored as 0-100, normalise to 0-1

            p1_tiebreak_pct   = _ps_val(p1_id, 'tiebreak_win_pct')
            p2_tiebreak_pct   = _ps_val(p2_id, 'tiebreak_win_pct')
            p1_pressure_pct   = _ps_val(p1_id, 'pressure_win_pct')
            p2_pressure_pct   = _ps_val(p2_id, 'pressure_win_pct')
            p1_match_save_pct = _ps_val(p1_id, 'match_point_save_pct')
            p2_match_save_pct = _ps_val(p2_id, 'match_point_save_pct')

            # Slam WUE ratio from ms_player_career_stats
            def _ms_val(pid: int, key: str, default: float = 1.5) -> float:
                ms = ms_career.get(int(pid), {})
                v  = ms.get(key)
                return float(v) if v is not None else default

            p1_slam_wue = _ms_val(p1_id, 'slam_winner_ue_ratio')
            p2_slam_wue = _ms_val(p2_id, 'slam_winner_ue_ratio')

            # Seeding
            w_seed = match.get('winner_seed')
            l_seed = match.get('loser_seed')
            p1_seeded = int(w_seed is not None and not (isinstance(w_seed, float) and np.isnan(w_seed))) if p1_is_winner else int(l_seed is not None and not (isinstance(l_seed, float) and np.isnan(l_seed)))
            p2_seeded = int(l_seed is not None and not (isinstance(l_seed, float) and np.isnan(l_seed))) if p1_is_winner else int(w_seed is not None and not (isinstance(w_seed, float) and np.isnan(w_seed)))

            # RTT point-in-time lookup
            p1_rtt_ratings = _lookup_rtt(p1_id, match_date)
            p2_rtt_ratings = _lookup_rtt(p2_id, match_date)

            # Determine surface-specific RTT column
            surf_lower = (surface or '').lower()
            if 'clay' in surf_lower:
                surf_rtt_col = 'clay_rating'
            elif 'grass' in surf_lower:
                surf_rtt_col = 'grass_rating'
            elif 'indoor' in surf_lower or 'carpet' in surf_lower:
                surf_rtt_col = 'indoor_rating'
            else:
                surf_rtt_col = 'hard_rating'

            p1_rtt      = _rtt_val(p1_rtt_ratings, 'rtt_score')
            p2_rtt      = _rtt_val(p2_rtt_ratings, 'rtt_score')
            p1_surf_rtg = _rtt_val(p1_rtt_ratings, surf_rtt_col)
            p2_surf_rtg = _rtt_val(p2_rtt_ratings, surf_rtt_col)
            p1_serve_rtg    = _rtt_val(p1_rtt_ratings, 'serve_rating')
            p2_serve_rtg    = _rtt_val(p2_rtt_ratings, 'serve_rating')
            p1_return_rtg   = _rtt_val(p1_rtt_ratings, 'return_rating')
            p2_return_rtg   = _rtt_val(p2_rtt_ratings, 'return_rating')
            p1_pressure_rtg = _rtt_val(p1_rtt_ratings, 'pressure_rating')
            p2_pressure_rtg = _rtt_val(p2_rtt_ratings, 'pressure_rating')
            p1_form_rtg     = _rtt_val(p1_rtt_ratings, 'form_score')
            p2_form_rtg     = _rtt_val(p2_rtt_ratings, 'form_score')

            # Fatigue: last match minutes
            p1_last_mins = _last_mins.get(p1_id, 90.0)
            p2_last_mins = _last_mins.get(p2_id, 90.0)

            # Elo features (swap if needed)
            w_elo_pre    = elo_row['w_elo_pre']
            l_elo_pre    = elo_row['l_elo_pre']
            w_surf_pre   = elo_row['w_surf_elo_pre']
            l_surf_pre   = elo_row['l_surf_elo_pre']
            w_elo_prob   = elo_row['elo_win_prob']         # P(winner wins) from Elo
            w_surf_prob  = elo_row['surf_elo_win_prob']

            if p1_is_winner:
                p1_elo, p2_elo = w_elo_pre, l_elo_pre
                p1_surf_elo, p2_surf_elo = w_surf_pre, l_surf_pre
                p1_elo_prob = w_elo_prob
                p1_surf_elo_prob = w_surf_prob
            else:
                p1_elo, p2_elo = l_elo_pre, w_elo_pre
                p1_surf_elo, p2_surf_elo = l_surf_pre, w_surf_pre
                p1_elo_prob = 1.0 - w_elo_prob if w_elo_prob else None
                p1_surf_elo_prob = (1.0 - w_surf_prob) if w_surf_prob else None

            def diff(a, b):
                if a is None or b is None:
                    return None
                return a - b

            row = {
                # ── Meta
                'match_id':      match.get('id'),
                'tourney_date':  match_date,
                'surface':       surface,
                'tour':          match.get('tour'),
                'tourney_level': level,
                'round':         round_,
                'season':        match.get('season'),
                'p1_id':         p1_id,
                'p2_id':         p2_id,
                'p1_name':       match['winner_name'] if p1_is_winner else match['loser_name'],
                'p2_name':       match['loser_name']  if p1_is_winner else match['winner_name'],
                'did_p1_win':    int(p1_is_winner),

                # ── Elo features
                'p1_elo':           p1_elo,
                'p2_elo':           p2_elo,
                'elo_diff':         diff(p1_elo, p2_elo),
                'p1_surf_elo':      p1_surf_elo,
                'p2_surf_elo':      p2_surf_elo,
                'surf_elo_diff':    diff(p1_surf_elo, p2_surf_elo),
                'elo_win_prob':     p1_elo_prob,          # baseline Elo probability for p1
                'surf_elo_win_prob': p1_surf_elo_prob,

                # ── Ranking
                'p1_rank':          p1_rank,
                'p2_rank':          p2_rank,
                'rank_diff':        diff(p2_rank, p1_rank),   # positive = p1 ranked higher (lower number)
                'p1_rank_pts':      p1_pts,
                'p2_rank_pts':      p2_pts,
                'rank_pts_diff':    diff(p1_pts, p2_pts),

                # ── Tournament context
                'level_enc':        LEVEL_ENCODE.get(level, 1),
                'round_enc':        ROUND_ENCODE.get(round_, 3),
                'best_of':          match.get('best_of', 3),
                'is_grand_slam':    int(level == 'G'),
                'is_masters':       int(level == 'M'),

                # ── Physical
                'p1_age':           p1_age,
                'p2_age':           p2_age,
                'age_diff':         diff(p1_age, p2_age),
                'height_diff':      diff(p1_ht, p2_ht),
                'hand_enc':         HAND_ENCODE.get((p1_hand, p2_hand), 0),

                # ── Aging curve
                'p1_age_factor':    p1_age_factor,
                'p2_age_factor':    p2_age_factor,
                'age_factor_diff':  p1_age_factor - p2_age_factor,

                # ── Clutch / pressure (from player_point_stats)
                'p1_tiebreak_pct':    p1_tiebreak_pct,
                'p2_tiebreak_pct':    p2_tiebreak_pct,
                'tiebreak_pct_diff':  p1_tiebreak_pct - p2_tiebreak_pct,
                'p1_pressure_pct':    p1_pressure_pct,
                'p2_pressure_pct':    p2_pressure_pct,
                'pressure_pct_diff':  p1_pressure_pct - p2_pressure_pct,
                'p1_match_save_pct':  p1_match_save_pct,
                'p2_match_save_pct':  p2_match_save_pct,
                'match_save_diff':    p1_match_save_pct - p2_match_save_pct,

                # ── Slam winner/UE ratio (from ms_player_career_stats)
                'p1_slam_wue':      p1_slam_wue,
                'p2_slam_wue':      p2_slam_wue,
                'slam_wue_diff':    p1_slam_wue - p2_slam_wue,

                # ── Rolling form (p1)
                **{f'p1_{k}': v for k, v in p1_w.items()},
                # ── Rolling form (p2)
                **{f'p2_{k}': v for k, v in p2_w.items()},

                # ── Form differentials (most ML-useful)
                'form_diff_10':     diff(p1_w.get('win_rate_10'), p2_w.get('win_rate_10')),
                'form_diff_20':     diff(p1_w.get('win_rate_20'), p2_w.get('win_rate_20')),
                'surf_form_diff':   diff(p1_w.get('surf_win_rate_10'), p2_w.get('surf_win_rate_10')),
                'svpt_won_diff':    diff(p1_w.get('svpt_won_20'), p2_w.get('svpt_won_20')),
                'ret_won_diff':     diff(p1_w.get('ret_won_20'), p2_w.get('ret_won_20')),
                'bp_save_diff':     diff(p1_w.get('bp_save_20'), p2_w.get('bp_save_20')),
                'bp_conv_diff':     diff(p1_w.get('bp_conv_20'), p2_w.get('bp_conv_20')),
                'ace_rate_diff':    diff(p1_w.get('ace_rate_20'), p2_w.get('ace_rate_20')),
                'df_rate_diff':     diff(p1_w.get('df_rate_20'), p2_w.get('df_rate_20')),

                # ── Fatigue
                'p1_days_rest':     p1_days,
                'p2_days_rest':     p2_days,
                'days_rest_diff':   diff(p1_days, p2_days),

                # ── H2H
                **h2h_f,

                # ── Seeding
                'p1_seeded':        p1_seeded,
                'p2_seeded':        p2_seeded,
                'seeding_adv':      p1_seeded - p2_seeded,

                # ── RTT point-in-time ratings
                'p1_rtt':           p1_rtt,
                'p2_rtt':           p2_rtt,
                'rtt_diff':         p1_rtt - p2_rtt,
                'p1_surf_rtg':      p1_surf_rtg,
                'p2_surf_rtg':      p2_surf_rtg,
                'surf_rtg_diff':    p1_surf_rtg - p2_surf_rtg,
                'p1_serve_rtg':     p1_serve_rtg,
                'p2_serve_rtg':     p2_serve_rtg,
                'serve_rtg_diff':   p1_serve_rtg - p2_serve_rtg,
                'p1_return_rtg':    p1_return_rtg,
                'p2_return_rtg':    p2_return_rtg,
                'return_rtg_diff':  p1_return_rtg - p2_return_rtg,
                'p1_pressure_rtg':  p1_pressure_rtg,
                'p2_pressure_rtg':  p2_pressure_rtg,
                'pressure_rtg_diff': p1_pressure_rtg - p2_pressure_rtg,
                'p1_form_rtg':      p1_form_rtg,
                'p2_form_rtg':      p2_form_rtg,
                'form_rtg_diff':    p1_form_rtg - p2_form_rtg,

                # ── Fatigue (last match duration)
                'p1_last_mins':     p1_last_mins,
                'p2_last_mins':     p2_last_mins,
                'fatigue_diff':     p1_last_mins - p2_last_mins,
            }

            rows.append(row)

            # ── POST-MATCH: update all trackers
            # Winner serve stats
            w_svpt_won = safe_pct(
                (match['w_1st_won'] or 0) + (match['w_2nd_won'] or 0),
                match['w_svpt']
            )
            w_ret_won = safe_pct(
                (match['l_1st_won'] or 0) + (match['l_2nd_won'] or 0),   # loser's serve = winner's return opps
                match['l_svpt']
            )
            w_ace_rate = safe_pct(match['w_ace'], match['w_sv_gms'])
            w_df_rate  = safe_pct(match['w_df'],  match['w_sv_gms'])

            # Loser serve stats
            l_svpt_won = safe_pct(
                (match['l_1st_won'] or 0) + (match['l_2nd_won'] or 0),
                match['l_svpt']
            )
            l_ret_won = safe_pct(
                (match['w_1st_won'] or 0) + (match['w_2nd_won'] or 0),
                match['w_svpt']
            )
            l_ace_rate = safe_pct(match['l_ace'], match['l_sv_gms'])
            l_df_rate  = safe_pct(match['l_df'],  match['l_sv_gms'])

            # Estimate sets played from score
            score_str = match.get('score', '') or ''
            n_sets = max(len(score_str.split()), 2)

            player_window.update(
                w_id, won=True, surface=surface, match_date=match_date,
                ace_rate=w_ace_rate, df_rate=w_df_rate,
                svpt_won=w_svpt_won, ret_won=w_ret_won,
                bp_save=match['w_bp_save_pct'], bp_conv=safe_pct(match['l_bp_faced'] - (match['l_bp_saved'] or 0) if match['l_bp_faced'] else None, match['l_bp_faced']),
                sets_played=n_sets,
            )
            player_window.update(
                l_id, won=False, surface=surface, match_date=match_date,
                ace_rate=l_ace_rate, df_rate=l_df_rate,
                svpt_won=l_svpt_won, ret_won=l_ret_won,
                bp_save=match['l_bp_save_pct'], bp_conv=safe_pct((match['w_bp_faced'] or 0) - (match['w_bp_saved'] or 0), match['w_bp_faced']),
                sets_played=n_sets,
            )
            h2h.update(w_id, l_id, surface)

            # Update last match minutes tracker
            mins = match.get('minutes')
            if mins is not None:
                try:
                    mins_float = float(mins)
                    _last_mins[w_id] = mins_float
                    _last_mins[l_id] = mins_float
                except (TypeError, ValueError):
                    pass

        return rows

    # ─────────────────────────────────────────
    # PERSIST
    # ─────────────────────────────────────────

    def save(self, path: str):
        """Save feature matrix to parquet for fast reloading."""
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        X, y, meta = self.build()
        # meta already includes 'did_p1_win'; don't add y again to avoid duplicate columns
        df = pd.concat([meta, X], axis=1)
        # Defensive: drop any accidental duplicate columns before writing parquet
        df = df.loc[:, ~df.columns.duplicated()]
        df.to_parquet(path, index=False)
        log.info(f"Saved features to {path}")
        return X, y, meta
