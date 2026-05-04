"""
ratethat.tennis — Surface-Specific Elo Engine
==============================================
Computes point-in-time Elo ratings for every player across all historical
matches. Four independent Elo tracks: Hard, Clay, Grass, Carpet/Indoor.
An overall Elo track is also maintained.

Key design principle: ZERO data leakage.
When computing features for match M, only matches played BEFORE M are used.
The Elo ratings stored are the PRE-MATCH ratings (before the result is known).

Usage:
    from ml.elo import EloEngine
    engine = EloEngine()
    engine.fit(matches_df)          # train on historical matches
    elos = engine.get_elos()        # DataFrame of player Elo history
    features = engine.match_features(matches_df)  # Elo diff per match

Reference:
    Kovalchik (2016) — Searching for the GOAT of tennis win prediction
    Base K=32, surface K=20 recommended for tennis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from collections import defaultdict
from typing import Optional


# ─────────────────────────────────────────────
# ELO CONFIG
# ─────────────────────────────────────────────

# K-factors: higher K = more volatile / adapts faster
K_OVERALL  = 32.0   # overall Elo
K_SURFACE  = 24.0   # surface Elo (slightly lower — fewer matches per surface)

# Tourney level multipliers (Grand Slams count more)
LEVEL_K_MULT = {
    'G': 1.5,   # Grand Slam
    'M': 1.3,   # Masters 1000 / Premier Mandatory
    'F': 1.2,   # Tour Finals / Year-end championships
    'A': 1.0,   # ATP 500/250 / Premier / International
    'D': 0.8,   # Davis Cup / Fed Cup
    'C': 0.7,   # Challenger / 125k
    'S': 0.5,   # Satellite / ITF
    'U': 0.5,   # Unknown
}

STARTING_ELO = 1500.0

# Surface normalisation — map Sackmann surface strings to our 4 tracks
SURFACE_MAP = {
    'Hard':        'hard',
    'Clay':        'clay',
    'Grass':       'grass',
    'Carpet':      'carpet',
    'Indoor Hard': 'carpet',   # treat indoor hard as carpet track
    'Indoor Clay': 'clay',
    'Unknown':     None,
}

ALL_SURFACES = ['hard', 'clay', 'grass', 'carpet']


def expected_score(elo_a: float, elo_b: float) -> float:
    """Expected win probability for player A given Elo ratings."""
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


class EloEngine:
    """
    Surface-specific Elo tracker.

    After fit(), call match_features() to get the pre-match Elo features
    for every match in the dataset (safe for ML training — no leakage).
    """

    def __init__(
        self,
        k_overall: float = K_OVERALL,
        k_surface: float = K_SURFACE,
        starting_elo: float = STARTING_ELO,
    ):
        self.k_overall  = k_overall
        self.k_surface  = k_surface
        self.starting   = starting_elo

        # Current Elo state per player
        self._overall: dict[int, float] = defaultdict(lambda: starting_elo)
        self._surface: dict[str, dict[int, float]] = {
            s: defaultdict(lambda: starting_elo) for s in ALL_SURFACES
        }

        # History: list of (player_id, match_date, elo_before, elo_after, surface)
        self._history: list[dict] = []

        # Per-match features computed during fit (no leakage)
        self._match_rows: list[dict] = []

    # ─────────────────────────────────────────
    # FIT
    # ─────────────────────────────────────────

    def fit(self, df: pd.DataFrame) -> "EloEngine":
        """
        Process matches chronologically, updating Elo after each match.
        df must have columns: winner_id, loser_id, tourney_date, surface,
                               tourney_level, tour, tourney_id, match_num
        """
        # Sort strictly by date then tour (ATP before WTA is arbitrary but consistent)
        df = df.sort_values(['tourney_date', 'tour', 'match_num'], na_position='last')

        for _, row in df.iterrows():
            w_id = row.get('winner_id')
            l_id = row.get('loser_id')

            if pd.isna(w_id) or pd.isna(l_id):
                continue

            w_id = int(w_id)
            l_id = int(l_id)

            surface_key = SURFACE_MAP.get(row.get('surface', 'Unknown'))
            level        = row.get('tourney_level', 'U') or 'U'
            k_mult       = LEVEL_K_MULT.get(level, 1.0)
            match_date   = row.get('tourney_date')

            # ── PRE-MATCH ratings (what we store as features)
            w_elo_before = self._overall[w_id]
            l_elo_before = self._overall[l_id]
            w_surf_before = self._surface[surface_key][w_id] if surface_key else None
            l_surf_before = self._surface[surface_key][l_id] if surface_key else None

            # ── Store per-match feature row (pre-match — no leakage)
            self._match_rows.append({
                'winner_id':        w_id,
                'loser_id':         l_id,
                'tourney_date':     match_date,
                'surface':          row.get('surface'),
                'tourney_level':    level,
                'tour':             row.get('tour'),
                'w_elo_pre':        w_elo_before,
                'l_elo_pre':        l_elo_before,
                'elo_diff':         w_elo_before - l_elo_before,   # positive = winner was favourite
                'w_surf_elo_pre':   w_surf_before,
                'l_surf_elo_pre':   l_surf_before,
                'surf_elo_diff':    (w_surf_before - l_surf_before) if surface_key else None,
                # Derived: expected win prob from Elo (calibration baseline)
                'elo_win_prob':     expected_score(w_elo_before, l_elo_before),
                'surf_elo_win_prob': expected_score(w_surf_before, l_surf_before) if surface_key else None,
            })

            # ── UPDATE overall Elo
            k_o = self.k_overall * k_mult
            e_w = expected_score(w_elo_before, l_elo_before)
            self._overall[w_id] += k_o * (1.0 - e_w)
            self._overall[l_id] += k_o * (0.0 - (1.0 - e_w))

            # ── UPDATE surface Elo
            if surface_key:
                k_s = self.k_surface * k_mult
                e_s = expected_score(w_surf_before, l_surf_before)
                self._surface[surface_key][w_id] += k_s * (1.0 - e_s)
                self._surface[surface_key][l_id] += k_s * (0.0 - (1.0 - e_s))

        return self

    # ─────────────────────────────────────────
    # OUTPUTS
    # ─────────────────────────────────────────

    def match_features(self) -> pd.DataFrame:
        """Return per-match Elo features (pre-match, no leakage)."""
        return pd.DataFrame(self._match_rows)

    def current_ratings(self) -> pd.DataFrame:
        """Return current (post all matches) Elo ratings for all players."""
        rows = []
        all_ids = set(self._overall.keys())
        for pid in all_ids:
            row = {
                'player_id':  pid,
                'elo_overall': self._overall[pid],
            }
            for s in ALL_SURFACES:
                row[f'elo_{s}'] = self._surface[s][pid]
            rows.append(row)
        return pd.DataFrame(rows)

    def player_elo(self, player_id: int) -> dict:
        """Get current Elo for a single player across all surfaces."""
        pid = int(player_id)
        return {
            'overall': self._overall[pid],
            **{f'elo_{s}': self._surface[s][pid] for s in ALL_SURFACES},
        }

    def win_probability(
        self,
        player1_id: int,
        player2_id: int,
        surface: Optional[str] = None,
    ) -> float:
        """
        Elo-based win probability for player1 vs player2.
        surface: 'hard' | 'clay' | 'grass' | 'carpet' | None (use overall)
        """
        p1 = int(player1_id)
        p2 = int(player2_id)
        if surface and surface in self._surface:
            e1 = self._surface[surface][p1]
            e2 = self._surface[surface][p2]
        else:
            e1 = self._overall[p1]
            e2 = self._overall[p2]
        return expected_score(e1, e2)
