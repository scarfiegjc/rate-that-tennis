"""
ratethat.tennis — Live Match Predictor
=======================================
Loads trained models and computes win probabilities for upcoming matches.
Writes results to the model_predictions table in PostgreSQL.

Also computes the key_factors JSON that powers the Intelligence tab:
which features most influenced this specific prediction, with human-
readable descriptions.

Usage:
    python -m ml.predict --match-id 12345
    python -m ml.predict --today         # predict all today's matches
    python -m ml.predict --upcoming 7   # predict next 7 days
"""

from __future__ import annotations

import os
import json
import math
import logging
import pickle
import warnings
import argparse
import unicodedata
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional
from datetime import date, timedelta

# Suppress LightGBM and sklearn feature-name validation warnings
warnings.filterwarnings("ignore", message=".*valid feature names.*")
warnings.filterwarnings("ignore", message=".*feature names.*")
warnings.filterwarnings("ignore", category=UserWarning, module="lightgbm")

import psycopg2
import psycopg2.extras

log = logging.getLogger("rtt-predict")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _get_model_feature_names(model) -> Optional[list]:
    """
    Extract the feature names that were used when training a model.
    Works for EnsembleModel (wraps XGBoost / LightGBM / Logistic) and individual estimators.
    Returns None if names can't be determined.
    """
    # EnsembleModel wraps several sub-models — recurse into the first one
    if hasattr(model, 'models'):
        for sub in model.models:
            names = _get_model_feature_names(sub)
            if names:
                return names
    # XGBoost: feature names stored in the booster
    if hasattr(model, 'get_booster'):
        try:
            names = model.get_booster().feature_names
            if names:
                return list(names)
        except Exception:
            pass
    # sklearn-style estimators (LogisticRegression, Pipeline, etc.)
    if hasattr(model, 'feature_names_in_') and model.feature_names_in_ is not None:
        return list(model.feature_names_in_)
    # LightGBM
    if hasattr(model, 'booster_'):
        try:
            return model.booster_.feature_name()
        except Exception:
            pass
    return None


class _RttUnpickler(pickle.Unpickler):
    """
    Models were saved when train.py ran as __main__, so EnsembleModel (and any
    other custom classes) are stored under the module name '__main__'.
    This unpickler redirects those lookups to ml.train where the classes live.
    """
    def find_class(self, module, name):
        if name == 'EnsembleModel' or module in ('__main__', 'ml.train'):
            try:
                from ml import train as _train_mod
                if hasattr(_train_mod, name):
                    return getattr(_train_mod, name)
            except Exception:
                pass
        return super().find_class(module, name)

DB_URL = (
    os.environ.get("DATABASE_PUBLIC_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway"
).strip()

MODELS_DIR  = Path(__file__).parent / "models"
RESULTS_DIR = Path(__file__).parent / "results"
MODEL_VERSION = "v2-namekey-elo-blend"

# ─────────────────────────────────────────────
# FACTOR DESCRIPTIONS
# These map feature names → human-readable explanations
# ─────────────────────────────────────────────

FACTOR_LABELS = {
    'surf_elo_diff':    "Surface Elo advantage",
    'elo_diff':         "Overall Elo rating advantage",
    'surf_form_diff':   "Recent form on this surface",
    'form_diff_10':     "Recent form (last 10 matches)",
    'form_diff_20':     "Recent form (last 20 matches)",
    'svpt_won_diff':    "Serve points won advantage",
    'ret_won_diff':     "Return points won advantage",
    'bp_save_diff':     "Break point saving ability",
    'bp_conv_diff':     "Break point conversion rate",
    'rank_diff':        "World ranking differential",
    'rank_pts_diff':    "Ranking points differential",
    'h2h_p1_win_pct':   "Head-to-head record",
    'h2h_surf_p1_win_pct': "H2H record on this surface",
    'days_rest_diff':   "Rest/fatigue advantage",
    'ace_rate_diff':    "Ace rate advantage",
    'height_diff':      "Height advantage (serve on fast surfaces)",
    'age_diff':         "Age/experience differential",
    'level_enc':        "Tournament level importance",
    'round_enc':        "Tournament stage pressure",
}

FACTOR_DIRECTION = {
    # For these features, positive value = p1 advantage
    'elo_diff', 'surf_elo_diff', 'form_diff_10', 'form_diff_20',
    'surf_form_diff', 'svpt_won_diff', 'ret_won_diff', 'bp_save_diff',
    'bp_conv_diff', 'rank_pts_diff',
}

FACTOR_NEGATIVE_DIRECTION = {
    # For these features, negative value = p1 advantage (lower rank = better)
    'rank_diff',  # rank_diff = p2_rank - p1_rank, positive = p1 ranked higher
}


def _sanitize_json(obj):
    """Recursively replace NaN / ±Inf with None so json.dumps produces valid JSON."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json(v) for v in obj]
    return obj


def describe_factor(feature: str, value: float, importance: float) -> dict:
    """Build a factor card for the Intelligence tab."""
    label = FACTOR_LABELS.get(feature, feature.replace('_', ' ').title())

    # Direction: is this helping p1 or p2?
    if feature in FACTOR_DIRECTION:
        favours = 'p1' if value > 0.01 else ('p2' if value < -0.01 else 'neutral')
    elif feature in FACTOR_NEGATIVE_DIRECTION:
        favours = 'p1' if value > 0.01 else ('p2' if value < -0.01 else 'neutral')
    else:
        favours = 'neutral'

    # Impact level based on feature importance
    if importance > 0.08:
        impact = 'high'
    elif importance > 0.03:
        impact = 'medium'
    else:
        impact = 'low'

    return {
        'feature':    feature,
        'label':      label,
        'value':      round(float(value), 4) if value is not None else None,
        'importance': round(float(importance), 4),
        'favours':    favours,
        'impact':     impact,
    }


# ─────────────────────────────────────────────
# LIVE PREDICTOR
# ─────────────────────────────────────────────

class LivePredictor:
    """
    Loads the trained models and computes predictions for matches
    in the production `matches` table.

    NOTE: This uses the live production matches table (not sa_matches).
    Player history is built from sa_matches and the live matches table
    to give the richest possible feature set.
    """

    def __init__(self, db_url: str = DB_URL, neutralise_rtt: bool = True):
        self.db_url = db_url
        self._models: dict[str, object] = {}
        self._elo_engine = None
        self._player_window = None
        self._h2h_tracker = None
        # See predict_match() — when True, RTT-derived features are forced to
        # the population median (50). Defaults to True until ml.ratings has
        # been rerun against the corrected match data.
        self.neutralise_rtt = neutralise_rtt
        # Player keying: normalised-name → synthetic int id used internally
        # by Elo / PlayerWindow / H2HTracker. This unifies Sackmann historical
        # data (where winner_id is often NULL but winner_name is reliable) with
        # live production data (where first_player_id is in a different keyspace
        # from sa_matches.winner_id). Production player_id is still used for
        # RTT-rating lookups, since player_ratings is keyed off it.
        self._name_to_pid: dict[str, int] = {}
        self._next_synth_id: int = 1
        self._prod_id_to_name: dict[int, str] = {}

    @staticmethod
    def _norm_name(name: Optional[str]) -> str:
        """Lower-case, strip diacritics, collapse whitespace.
        Matches the convention in pipeline/merge_duplicate_players.py so the
        production-side merge and the predictor's keying agree."""
        if not name:
            return ""
        s = str(name).strip().lower()
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        return " ".join(s.split())

    def _key(self, name: Optional[str]) -> Optional[int]:
        """Translate a player name to a stable synthetic int id.
        Returns None if name is empty (caller should skip the row)."""
        norm = self._norm_name(name)
        if not norm:
            return None
        pid = self._name_to_pid.get(norm)
        if pid is None:
            pid = self._next_synth_id
            self._name_to_pid[norm] = pid
            self._next_synth_id += 1
        return pid

    def _key_for_prod_id(self, prod_id: Optional[int]) -> Optional[int]:
        """Translate a production players.id → synthetic Elo/window/H2H key
        via the cached prod_id → full_name map populated in load_player_history."""
        if prod_id is None:
            return None
        name = self._prod_id_to_name.get(int(prod_id))
        if not name:
            return None
        return self._key(name)

    def load_models(self) -> "LivePredictor":
        """
        Load trained model artefacts from disk.
        Skips gracefully if files are missing — predictions fall back to Elo.
        """
        if not MODELS_DIR.exists():
            log.info("ml/models/ directory not found — predictions will use Elo fallback")
            return self

        try:
            from ml.train import EnsembleModel  # noqa: F401 — needed for pickle
        except ImportError:
            pass

        for surface in ['overall', 'hard', 'clay', 'grass']:
            for model_type in ['ensemble', 'xgboost', 'lightgbm', 'logistic']:
                label = surface if surface == 'overall' else surface.capitalize()
                path = MODELS_DIR / f"{label}_{model_type}.pkl"
                if path.exists():
                    try:
                        with open(path, 'rb') as f:
                            self._models[f"{surface}_{model_type}"] = _RttUnpickler(f).load()
                        log.info(f"  Loaded model: {surface}_{model_type} (from {path.name})")
                    except Exception as e:
                        log.warning(f"  Could not load {path.name}: {e}")

        if not self._models:
            log.info("No model files found — predictions will use Elo fallback")
        else:
            log.info(f"  {len(self._models)} model(s) loaded")
        return self

    def _get_model(self, surface: Optional[str]) -> tuple[object, str]:
        """Get the best available model for this surface."""
        if surface:
            surf_lower = surface.lower()
            for model_type in ['ensemble', 'xgboost', 'lightgbm', 'logistic']:
                key = f"{surf_lower}_{model_type}"
                if key in self._models:
                    return self._models[key], key
        # Fall back to overall
        for model_type in ['ensemble', 'xgboost', 'lightgbm', 'logistic']:
            key = f"overall_{model_type}"
            if key in self._models:
                return self._models[key], key
        raise RuntimeError("No models loaded")

    def load_player_history(self, years_back: Optional[int] = None) -> "LivePredictor":
        """
        Load historical match data (both sa_matches and live matches) to
        build Elo ratings and rolling stats for all active players.

        years_back: optional cutoff — only load matches from the last N years.
                    None = full history. Setting this (e.g. 8) speeds up the
                    Elo fit by 4–5× with negligible loss for current-form
                    predictions, since pre-cutoff matches mostly contribute
                    to long-retired players' ratings.
        """
        from ml.elo import EloEngine, SURFACE_MAP
        from ml.features import PlayerWindow, H2HTracker, safe_pct
        from datetime import date as _date, timedelta as _td

        if years_back:
            cutoff_date = _date.today() - _td(days=int(years_back) * 365)
            log.info(f"Building player history from sa_matches + live matches "
                     f"(cutoff={cutoff_date}) ...")
        else:
            cutoff_date = None
            log.info("Building player history from sa_matches + live matches ...")

        conn = psycopg2.connect(self.db_url)
        conn.cursor_factory = psycopg2.extras.RealDictCursor

        try:
            # Cache prod_id → full_name so predict_match() can translate live
            # player_ids into the same name-based key space.
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, COALESCE(NULLIF(TRIM(full_name), ''), name) AS name
                    FROM players
                    WHERE COALESCE(NULLIF(TRIM(full_name), ''), name) IS NOT NULL
                """)
                for r in cur.fetchall():
                    self._prod_id_to_name[int(r['id'])] = r['name']

            # Load from sa_matches (historical) — key by NAME, not id, because
            # ~77k recent rows have NULL winner_id even though winner_name is
            # populated, and Sackmann ID space ≠ production players.id space.
            sa_cutoff_clause = "AND tourney_date >= %s" if cutoff_date else ""
            sa_params = (cutoff_date,) if cutoff_date else ()
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT
                        winner_name, loser_name,
                        tourney_date, surface, tourney_level,
                        tour, match_num, score,
                        w_svpt, w_1st_won, w_2nd_won, w_sv_gms, w_ace, w_df,
                        w_bp_saved, w_bp_faced, w_bp_save_pct,
                        l_svpt, l_1st_won, l_2nd_won, l_sv_gms, l_ace, l_df,
                        l_bp_saved, l_bp_faced, l_bp_save_pct
                    FROM sa_matches
                    WHERE tourney_date IS NOT NULL
                      AND winner_name IS NOT NULL AND TRIM(winner_name) <> ''
                      AND loser_name  IS NOT NULL AND TRIM(loser_name)  <> ''
                      {sa_cutoff_clause}
                    ORDER BY tourney_date, match_num
                """, sa_params)
                sa_rows = cur.fetchall()

            # Load from live matches table — also key by NAME (joined from
            # players.full_name) so the live history merges into the same
            # player buckets as the Sackmann history.
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COALESCE(NULLIF(TRIM(p1.full_name), ''), p1.name) AS winner_name,
                        COALESCE(NULLIF(TRIM(p2.full_name), ''), p2.name) AS loser_name,
                        m.event_date       AS tourney_date,
                        s.name             AS surface,
                        NULL               AS tourney_level,
                        'ATP'              AS tour,
                        0                  AS match_num,
                        m.final_result     AS score
                    FROM matches m
                    LEFT JOIN tournaments t ON t.id = m.tournament_id
                    LEFT JOIN surfaces s    ON s.id = t.surface_id
                    JOIN players p1 ON p1.id = m.first_player_id
                    JOIN players p2 ON p2.id = m.second_player_id
                    WHERE m.event_status = 'Finished'
                      AND m.winner = 'First Player'
                      AND COALESCE(NULLIF(TRIM(p1.full_name), ''), p1.name) IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(p2.full_name), ''), p2.name) IS NOT NULL
                    UNION ALL
                    SELECT
                        COALESCE(NULLIF(TRIM(p2.full_name), ''), p2.name) AS winner_name,
                        COALESCE(NULLIF(TRIM(p1.full_name), ''), p1.name) AS loser_name,
                        m.event_date       AS tourney_date,
                        s.name             AS surface,
                        NULL               AS tourney_level,
                        'ATP'              AS tour,
                        0                  AS match_num,
                        m.final_result     AS score
                    FROM matches m
                    LEFT JOIN tournaments t ON t.id = m.tournament_id
                    LEFT JOIN surfaces s    ON s.id = t.surface_id
                    JOIN players p1 ON p1.id = m.first_player_id
                    JOIN players p2 ON p2.id = m.second_player_id
                    WHERE m.event_status = 'Finished'
                      AND m.winner = 'Second Player'
                      AND COALESCE(NULLIF(TRIM(p1.full_name), ''), p1.name) IS NOT NULL
                      AND COALESCE(NULLIF(TRIM(p2.full_name), ''), p2.name) IS NOT NULL
                    ORDER BY tourney_date
                """)
                live_rows = cur.fetchall()

        finally:
            conn.close()

        # Combine
        all_rows = list(sa_rows) + list(live_rows)
        df_hist = pd.DataFrame(all_rows)
        df_hist['tourney_date'] = pd.to_datetime(df_hist['tourney_date'])
        df_hist = df_hist.sort_values('tourney_date')

        # Translate names → synthetic int ids consumed by EloEngine /
        # PlayerWindow / H2HTracker (all of which `int()` their player_id arg).
        df_hist['winner_id'] = df_hist['winner_name'].map(self._key)
        df_hist['loser_id']  = df_hist['loser_name'].map(self._key)
        df_hist = df_hist.dropna(subset=['winner_id', 'loser_id'])
        df_hist['winner_id'] = df_hist['winner_id'].astype(int)
        df_hist['loser_id']  = df_hist['loser_id'].astype(int)

        log.info(f"  {len(df_hist):,} historical matches loaded "
                 f"({len(self._name_to_pid):,} unique players)")

        # Fit Elo
        self._elo_engine = EloEngine()
        self._elo_engine.fit(df_hist)

        # Build rolling stats and H2H
        self._player_window = PlayerWindow(max_window=50)
        self._h2h_tracker   = H2HTracker()

        for _, row in df_hist.iterrows():
            w_id = row.get('winner_id')
            l_id = row.get('loser_id')
            if pd.isna(w_id) or pd.isna(l_id):
                continue
            w_id, l_id = int(w_id), int(l_id)
            surface = row.get('surface')
            date    = row['tourney_date']

            w_svpt_won = safe_pct(
                (row.get('w_1st_won') or 0) + (row.get('w_2nd_won') or 0),
                row.get('w_svpt')
            )
            l_svpt_won = safe_pct(
                (row.get('l_1st_won') or 0) + (row.get('l_2nd_won') or 0),
                row.get('l_svpt')
            )
            w_ret_won = safe_pct(
                (row.get('l_1st_won') or 0) + (row.get('l_2nd_won') or 0),
                row.get('l_svpt')
            )
            l_ret_won = safe_pct(
                (row.get('w_1st_won') or 0) + (row.get('w_2nd_won') or 0),
                row.get('w_svpt')
            )

            # BP conversion: winner converts loser's BP faced - saved; loser converts winner's
            w_bp_conv = safe_pct(
                (row.get('l_bp_faced') or 0) - (row.get('l_bp_saved') or 0),
                row.get('l_bp_faced')
            ) if row.get('l_bp_faced') else None
            l_bp_conv = safe_pct(
                (row.get('w_bp_faced') or 0) - (row.get('w_bp_saved') or 0),
                row.get('w_bp_faced')
            ) if row.get('w_bp_faced') else None

            # bp_save_pct comes back from PostgreSQL as decimal.Decimal which
            # breaks np.mean() in PlayerWindow.get_stats() — coerce to float.
            def _f(v):
                return float(v) if v is not None else None

            self._player_window.update(w_id, won=True,  surface=surface, match_date=date,
                                       svpt_won=_f(w_svpt_won), ret_won=_f(w_ret_won),
                                       ace_rate=_f(safe_pct(row.get('w_ace'), row.get('w_sv_gms'))),
                                       df_rate=_f(safe_pct(row.get('w_df'), row.get('w_sv_gms'))),
                                       bp_save=_f(row.get('w_bp_save_pct')),
                                       bp_conv=_f(w_bp_conv))
            self._player_window.update(l_id, won=False, surface=surface, match_date=date,
                                       svpt_won=_f(l_svpt_won), ret_won=_f(l_ret_won),
                                       ace_rate=_f(safe_pct(row.get('l_ace'), row.get('l_sv_gms'))),
                                       df_rate=_f(safe_pct(row.get('l_df'), row.get('l_sv_gms'))),
                                       bp_save=_f(row.get('l_bp_save_pct')),
                                       bp_conv=_f(l_bp_conv))
            self._h2h_tracker.update(w_id, l_id, surface)

        log.info("  Player history built")
        return self

    def predict_match(
        self,
        match_id: int,
        p1_id: int,
        p2_id: int,
        surface: Optional[str],
        tourney_level: str,
        round_: str,
        best_of: int,
        p1_rank: Optional[int],
        p2_rank: Optional[int],
        p1_rank_pts: Optional[int],
        p2_rank_pts: Optional[int],
        p1_age: Optional[float],
        p2_age: Optional[float],
        p1_ht: Optional[int],
        p2_ht: Optional[int],
        p1_hand: Optional[str],
        p2_hand: Optional[str],
        match_date=None,
    ) -> dict:
        """
        Compute prediction for a single match.
        Returns dict ready for model_predictions table + Intelligence tab.
        """
        from ml.features import ROUND_ENCODE, LEVEL_ENCODE, HAND_ENCODE
        from ml.elo import SURFACE_MAP

        surf_key = SURFACE_MAP.get(surface or '', None)

        # ── Translate the production player ids to the name-based synthetic
        # keys used by the Elo / window / H2H trackers (see load_player_history).
        # Falls back to the raw id if the player has no full_name on file —
        # they will still get whatever live-match Elo accrued under that key.
        p1_skey = self._key_for_prod_id(p1_id) or int(p1_id)
        p2_skey = self._key_for_prod_id(p2_id) or int(p2_id)

        # ── Elo features
        p1_elo = self._elo_engine.player_elo(p1_skey)
        p2_elo = self._elo_engine.player_elo(p2_skey)
        p1_elo_overall = p1_elo['overall']
        p2_elo_overall = p2_elo['overall']
        p1_surf_elo = p1_elo.get(f'elo_{surf_key}') if surf_key else None
        p2_surf_elo = p2_elo.get(f'elo_{surf_key}') if surf_key else None

        from ml.elo import expected_score
        elo_win_prob      = expected_score(p1_elo_overall, p2_elo_overall)
        surf_elo_win_prob = expected_score(p1_surf_elo, p2_surf_elo) if surf_key else None

        # ── Rolling stats
        p1_w = self._player_window.get_stats(p1_skey, surface, [10, 20, 50])
        p2_w = self._player_window.get_stats(p2_skey, surface, [10, 20, 50])
        p1_days = self._player_window.days_since_last(p1_skey, match_date)
        p2_days = self._player_window.days_since_last(p2_skey, match_date)

        # ── H2H
        h2h_f = self._h2h_tracker.get(p1_skey, p2_skey, surface)

        # ── RTT ratings from player_ratings table.
        # When `neutralise_rtt` is set, every RTT-derived feature is forced
        # to the population median (50). Use this when the player_ratings
        # table is known to be stale (e.g. recently after a duplicate-merge
        # or a name-keying change to the predictor) — it stops the model
        # being misled by miscomputed scores. The flag defaults to True
        # until ml.ratings has been rerun on the corrected match data.
        def _fetch_player_ratings(pid: int) -> dict:
            try:
                _conn = psycopg2.connect(self.db_url)
                _conn.cursor_factory = psycopg2.extras.RealDictCursor
                with _conn.cursor() as cur:
                    cur.execute("""
                        SELECT rtt_score, clay_rating, hard_rating, grass_rating, indoor_rating,
                               serve_rating, return_rating, pressure_rating, form_score
                        FROM player_ratings WHERE player_id = %s
                    """, (pid,))
                    row = cur.fetchone()
                _conn.close()
                return dict(row) if row else {}
            except Exception:
                return {}

        if getattr(self, 'neutralise_rtt', True):
            p1_rtt_val = p2_rtt_val = 50.0
            p1_surf_rtg_val = p2_surf_rtg_val = 50.0
            p1_serve_rtg = p2_serve_rtg = 50.0
            p1_return_rtg = p2_return_rtg = 50.0
            p1_pressure_rtg = p2_pressure_rtg = 50.0
            p1_form_rtg = p2_form_rtg = 50.0
        else:
            # Use the prefetched cache when predict_upcoming has populated it.
            cached_rtt = getattr(self, '_rtt_by_pid', None)
            if cached_rtt is not None:
                p1_rtg = cached_rtt.get(p1_id, {})
                p2_rtg = cached_rtt.get(p2_id, {})
            else:
                p1_rtg = _fetch_player_ratings(p1_id)
                p2_rtg = _fetch_player_ratings(p2_id)

            def _rtg(ratings: dict, key: str) -> float:
                v = ratings.get(key)
                return float(v) if v is not None else 50.0

            # Determine surface column for RTT
            surf_lower = (surface or '').lower()
            if 'clay' in surf_lower:
                surf_rtt_col = 'clay_rating'
            elif 'grass' in surf_lower:
                surf_rtt_col = 'grass_rating'
            elif 'indoor' in surf_lower or 'carpet' in surf_lower:
                surf_rtt_col = 'indoor_rating'
            else:
                surf_rtt_col = 'hard_rating'

            p1_rtt_val      = _rtg(p1_rtg, 'rtt_score')
            p2_rtt_val      = _rtg(p2_rtg, 'rtt_score')
            p1_surf_rtg_val = _rtg(p1_rtg, surf_rtt_col)
            p2_surf_rtg_val = _rtg(p2_rtg, surf_rtt_col)
            p1_serve_rtg    = _rtg(p1_rtg, 'serve_rating')
            p2_serve_rtg    = _rtg(p2_rtg, 'serve_rating')
            p1_return_rtg   = _rtg(p1_rtg, 'return_rating')
            p2_return_rtg   = _rtg(p2_rtg, 'return_rating')
            p1_pressure_rtg = _rtg(p1_rtg, 'pressure_rating')
            p2_pressure_rtg = _rtg(p2_rtg, 'pressure_rating')
            p1_form_rtg     = _rtg(p1_rtg, 'form_score')
            p2_form_rtg     = _rtg(p2_rtg, 'form_score')

        def diff(a, b):
            if a is None or b is None:
                return None
            return a - b

        features = {
            'p1_elo':           p1_elo_overall,
            'p2_elo':           p2_elo_overall,
            'elo_diff':         diff(p1_elo_overall, p2_elo_overall),
            'p1_surf_elo':      p1_surf_elo,
            'p2_surf_elo':      p2_surf_elo,
            'surf_elo_diff':    diff(p1_surf_elo, p2_surf_elo),
            'elo_win_prob':     elo_win_prob,
            'surf_elo_win_prob': surf_elo_win_prob,
            'p1_rank':          p1_rank,
            'p2_rank':          p2_rank,
            'rank_diff':        diff(p2_rank, p1_rank),
            'p1_rank_pts':      p1_rank_pts,
            'p2_rank_pts':      p2_rank_pts,
            'rank_pts_diff':    diff(p1_rank_pts, p2_rank_pts),
            'level_enc':        LEVEL_ENCODE.get(tourney_level, 1),
            'round_enc':        ROUND_ENCODE.get(round_, 3),
            'best_of':          best_of,
            'is_grand_slam':    int(tourney_level == 'G'),
            'is_masters':       int(tourney_level == 'M'),
            'p1_age':           p1_age,
            'p2_age':           p2_age,
            'age_diff':         diff(p1_age, p2_age),
            'height_diff':      diff(p1_ht, p2_ht),
            'hand_enc':         HAND_ENCODE.get((p1_hand, p2_hand), 0),
            **{f'p1_{k}': v for k, v in p1_w.items()},
            **{f'p2_{k}': v for k, v in p2_w.items()},
            'form_diff_10':     diff(p1_w.get('win_rate_10'), p2_w.get('win_rate_10')),
            'form_diff_20':     diff(p1_w.get('win_rate_20'), p2_w.get('win_rate_20')),
            'surf_form_diff':   diff(p1_w.get('surf_win_rate_10'), p2_w.get('surf_win_rate_10')),
            'svpt_won_diff':    diff(p1_w.get('svpt_won_20'), p2_w.get('svpt_won_20')),
            'ret_won_diff':     diff(p1_w.get('ret_won_20'), p2_w.get('ret_won_20')),
            'bp_save_diff':     diff(p1_w.get('bp_save_20'), p2_w.get('bp_save_20')),
            'bp_conv_diff':     diff(p1_w.get('bp_conv_20'), p2_w.get('bp_conv_20')),
            'ace_rate_diff':    diff(p1_w.get('ace_rate_20'), p2_w.get('ace_rate_20')),
            'df_rate_diff':     diff(p1_w.get('df_rate_20'), p2_w.get('df_rate_20')),
            'p1_days_rest':     p1_days,
            'p2_days_rest':     p2_days,
            'days_rest_diff':   diff(p1_days, p2_days),
            **h2h_f,

            # ── RTT ratings (from player_ratings table)
            'p1_rtt':           p1_rtt_val,
            'p2_rtt':           p2_rtt_val,
            'rtt_diff':         p1_rtt_val - p2_rtt_val,
            'p1_surf_rtg':      p1_surf_rtg_val,
            'p2_surf_rtg':      p2_surf_rtg_val,
            'surf_rtg_diff':    p1_surf_rtg_val - p2_surf_rtg_val,
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
        }

        # ── Bookmaker implied probability (high-value signal)
        # bookmaker_odds schema is one row per (match_id, bookmaker, player_ref)
        # where player_ref ∈ {'first_player','second_player'}. Average the
        # implied_prob across books per side, then de-vig.
        # When predict_upcoming has prefetched odds in bulk (self._odds_by_mid)
        # use the cache; otherwise fall back to a per-match SQL hit.
        ip = None
        cached = getattr(self, '_odds_by_mid', None)
        if cached is not None:
            ip = cached.get(match_id)
        if ip is None:
            try:
                _bk_conn = psycopg2.connect(self.db_url)
                _bk_conn.cursor_factory = psycopg2.extras.RealDictCursor
                with _bk_conn.cursor() as cur:
                    cur.execute("""
                        SELECT player_ref, AVG(implied_prob) AS p
                        FROM bookmaker_odds
                        WHERE match_id = %s
                        GROUP BY player_ref
                    """, (match_id,))
                    odds_rows = cur.fetchall()
                _bk_conn.close()
                ip = {r['player_ref']: float(r['p']) for r in odds_rows if r['p'] is not None}
            except Exception:
                ip = {}
        ip1 = ip.get('first_player') if ip else None
        ip2 = ip.get('second_player') if ip else None
        if ip1 is not None and ip2 is not None and (ip1 + ip2) > 0:
            features['market_impl_p1'] = ip1 / (ip1 + ip2)
        else:
            features['market_impl_p1'] = 0.5

        # ── Predict — surface-Elo-led with optional model refinement.
        #
        # The trained logistic / XGBoost / LightGBM models in ml/models/ were
        # fit on features built BEFORE the name-keyed Elo fix (when modern top
        # players had NULL winner_id in sa_matches and were skipped). Their
        # response surface is miscalibrated for the corrected Elo distribution
        # and inverts on some moderate-favourite matches (Rublev/Tiafoe-style).
        #
        # Until the models are retrained on corrected features, take the
        # surface-Elo expected score as the primary signal and only blend in
        # the model output when it agrees with Elo on direction.
        elo_prob = surf_elo_win_prob if surf_elo_win_prob is not None else elo_win_prob
        elo_prob = max(0.02, min(0.98, elo_prob))   # clamp away from 0/1
        model_prob: Optional[float] = None
        model_key = 'elo'
        if self._models:
            try:
                model, model_key = self._get_model(surface)
                feat_names = _get_model_feature_names(model)
                if not feat_names:
                    from ml.train import CORE_FEATURES
                    feat_names = CORE_FEATURES
                X = pd.DataFrame([{k: features.get(k) for k in feat_names}])
                model_prob = float(model.predict_proba(X)[0, 1])
            except Exception as e:
                log.debug(f"Model prediction failed ({e}), falling back to Elo")
                model_prob = None
                model_key = 'elo'

        # Blend only when model and Elo agree on direction. On disagreement,
        # trust Elo — it's grounded in the corrected name-keyed history.
        if model_prob is not None and (model_prob - 0.5) * (elo_prob - 0.5) > 0:
            prob_p1 = 0.7 * elo_prob + 0.3 * model_prob
        else:
            prob_p1 = elo_prob
            if model_prob is not None:
                model_key = f"{model_key}+elo_override"
        prob_p2 = 1.0 - prob_p1

        # ── Confidence tier
        edge = abs(prob_p1 - 0.5)
        if edge >= 0.20:
            confidence = 'high'
        elif edge >= 0.10:
            confidence = 'medium'
        else:
            confidence = 'low'

        # ── Key factors for Intelligence tab
        # Use feature value × rough importance proxy (elo gets highest weight)
        importance_proxy = {
            'surf_elo_diff': 0.15, 'elo_diff': 0.12, 'surf_elo_win_prob': 0.10,
            'elo_win_prob': 0.09, 'surf_form_diff': 0.07, 'form_diff_10': 0.06,
            'svpt_won_diff': 0.05, 'ret_won_diff': 0.05, 'rank_diff': 0.04,
            'bp_save_diff': 0.04, 'bp_conv_diff': 0.03, 'h2h_p1_win_pct': 0.04,
            'h2h_surf_p1_win_pct': 0.03, 'days_rest_diff': 0.02,
            'form_diff_20': 0.03, 'ace_rate_diff': 0.02, 'age_diff': 0.01,
        }

        key_factors = []
        for feat, imp in sorted(importance_proxy.items(), key=lambda x: -x[1]):
            val = features.get(feat)
            if val is not None and feat in FACTOR_LABELS:
                key_factors.append(describe_factor(feat, val, imp))
            if len(key_factors) >= 8:
                break

        return {
            'match_id':          match_id,
            'prob_first_player': round(prob_p1, 4),
            'prob_second_player': round(prob_p2, 4),
            'confidence':        confidence,
            'key_factors':       key_factors,
            'model_version':     MODEL_VERSION,
            'model_key':         model_key,
            'elo_baseline':      round(elo_win_prob, 4),
            'surf_elo_baseline': round(surf_elo_win_prob, 4) if surf_elo_win_prob else None,
            'edge_vs_elo':       round(abs(prob_p1 - elo_win_prob), 4),
        }

    def write_prediction(self, prediction: dict):
        """Write a single prediction to the model_predictions table.

        Uses a persistent self._write_conn when available (set by
        predict_upcoming) so the per-match loop avoids reconnecting to the
        DB on every write — that round-trip dominated the loop time."""
        wconn = getattr(self, '_write_conn', None)
        owns_conn = wconn is None
        if wconn is None:
            wconn = psycopg2.connect(self.db_url)
        try:
            with wconn.cursor() as cur:
                # Sanitize key_factors: NaN/Inf → None (otherwise jsonb rejects them)
                clean_factors = _sanitize_json(prediction['key_factors'])
                cur.execute("""
                    INSERT INTO model_predictions
                        (match_id, prob_first_player, prob_second_player, confidence,
                         key_factors, model_version)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (match_id) DO UPDATE SET
                        prob_first_player  = EXCLUDED.prob_first_player,
                        prob_second_player = EXCLUDED.prob_second_player,
                        confidence         = EXCLUDED.confidence,
                        key_factors        = EXCLUDED.key_factors,
                        model_version      = EXCLUDED.model_version,
                        predicted_at       = NOW()
                """, (
                    prediction['match_id'],
                    prediction['prob_first_player'],
                    prediction['prob_second_player'],
                    prediction['confidence'],
                    json.dumps(clean_factors),
                    prediction['model_version'],
                ))
            # Only auto-commit when this call owns the connection. When
            # predict_upcoming holds a persistent self._write_conn, defer
            # the commit to the end of the loop to avoid a per-match
            # network round-trip.
            if owns_conn:
                wconn.commit()
        finally:
            if owns_conn:
                wconn.close()

    def _lookup_rank(self, player_id: int, conn) -> tuple[Optional[int], Optional[int]]:
        """
        Fetch current ranking and ranking points for a player from sa_matches
        via player name lookup. Returns (rank, rank_pts) or (None, None).
        """
        try:
            with conn.cursor() as cur:
                # Get player name from production players table
                cur.execute(
                    "SELECT name, full_name FROM players WHERE id = %s",
                    (player_id,)
                )
                row = cur.fetchone()
            if not row:
                return None, None
            name, full_name = row[0], row[1]
            # Get last token of full name or name for fuzzy match
            last_token = None
            for n in (full_name, name):
                if n:
                    tokens = n.replace('.', '').split()
                    if tokens:
                        last_token = tokens[-1].strip()
                        if last_token and len(last_token) >= 3:
                            break
            if not last_token:
                return None, None
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COALESCE(
                            MIN(sm.winner_rank) FILTER (WHERE sm.winner_id = sp.player_id),
                            MIN(sm.loser_rank)  FILTER (WHERE sm.loser_id  = sp.player_id)
                        ) AS rank,
                        COALESCE(
                            MAX(sm.winner_rank_points) FILTER (WHERE sm.winner_id = sp.player_id),
                            MAX(sm.loser_rank_points)  FILTER (WHERE sm.loser_id  = sp.player_id)
                        ) AS rank_pts
                    FROM sa_players sp
                    JOIN sa_matches sm ON (sm.winner_id = sp.player_id OR sm.loser_id = sp.player_id)
                    WHERE sp.full_name ILIKE %s
                      AND sm.tourney_date >= CURRENT_DATE - INTERVAL '2 years'
                """, (f"%{last_token}%",))
                r = cur.fetchone()
            if r and r[0]:
                return int(r[0]), (int(r[1]) if r[1] else None)
            return None, None
        except Exception:
            return None, None

    @staticmethod
    def _tour_category_to_level(tour_category: Optional[str], type_name: Optional[str]) -> str:
        """
        Map api-tennis tour_category / type_name → Sackmann tourney_level code.
        G=GrandSlam, M=Masters/Premier, A=ATP250/500/WTA, C=Challenger, S/D=ITF
        """
        tc  = (tour_category or '').lower()
        tn  = (type_name or '').lower()
        if 'grand slam' in tn or 'grand_slam' in tn:
            return 'G'
        if 'masters' in tn or 'premier mandatory' in tn or 'premier 5' in tn:
            return 'M'
        if 'challenger' in tc or 'challenger' in tn:
            return 'C'
        if 'itf' in tc or 'itf' in tn:
            return 'S'
        if 'junior' in tc or 'junior' in tn:
            return 'S'
        if 'exhibition' in tc:
            return 'S'
        if 'teams' in tc or 'davis' in tn or 'cup' in tn:
            return 'D'
        # Default: ATP/WTA main tour = A
        return 'A'

    @staticmethod
    def _age_at(birthday, match_date) -> Optional[float]:
        """Return age in years at match_date, from birthday. Returns None if either is missing."""
        if birthday is None or match_date is None:
            return None
        try:
            from datetime import date as _date
            md = match_date.date() if hasattr(match_date, 'date') else (
                _date.fromisoformat(str(match_date)[:10])
            )
            bd = birthday.date() if hasattr(birthday, 'date') else (
                _date.fromisoformat(str(birthday)[:10])
            )
            return round((md - bd).days / 365.25, 1)
        except Exception:
            return None

    def predict_upcoming(self, days_ahead: int = 1, skip_existing: bool = False):
        """Predict all upcoming matches in the production matches table.

        Pre-fetches player_ratings, bookmaker_odds, and ranks in bulk so the
        per-match prediction loop avoids per-row DB round-trips. This was
        the main bottleneck preventing the predictor from running inside
        short shell windows.

        skip_existing: when True, skip matches that already have a prediction
                       at the current MODEL_VERSION (idempotent re-runs)."""
        conn = psycopg2.connect(self.db_url)
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)

        skip_clause = ""
        if skip_existing:
            skip_clause = """
                AND NOT EXISTS (
                    SELECT 1 FROM model_predictions mp
                    WHERE mp.match_id = m.id AND mp.model_version = %s
                )
            """

        try:
            with conn.cursor() as cur:
                params = [str(today), str(cutoff)]
                if skip_existing:
                    params.append(MODEL_VERSION)
                cur.execute(f"""
                    SELECT
                        m.id AS match_id,
                        m.first_player_id,
                        m.second_player_id,
                        m.event_date,
                        m.tournament_round AS round,
                        m.is_doubles,
                        3 AS best_of,
                        t.surface_id,
                        s.name AS surface,
                        et.tour_category,
                        et.type_name,
                        p1.height_cm      AS p1_ht,
                        p1.hand           AS p1_hand,
                        p1.birthday       AS p1_birthday,
                        p2.height_cm      AS p2_ht,
                        p2.hand           AS p2_hand,
                        p2.birthday       AS p2_birthday
                    FROM matches m
                    LEFT JOIN tournaments t ON m.tournament_id = t.id
                    LEFT JOIN surfaces s ON t.surface_id = s.id
                    LEFT JOIN event_types et ON m.event_type_id = et.id
                    LEFT JOIN players p1 ON p1.id = m.first_player_id
                    LEFT JOIN players p2 ON p2.id = m.second_player_id
                    WHERE m.event_date BETWEEN %s AND %s
                      AND m.event_status NOT IN ('Finished', 'Cancelled', 'Retired')
                      AND m.first_player_id IS NOT NULL
                      AND m.second_player_id IS NOT NULL
                      AND (m.is_doubles IS NULL OR m.is_doubles = FALSE)
                      {skip_clause}
                """, tuple(params))
                upcoming = cur.fetchall()

            # ── Bulk prefetches keyed by player_id / match_id
            pids = set()
            mids = []
            for m in upcoming:
                pids.add(m['first_player_id']); pids.add(m['second_player_id'])
                mids.append(m['match_id'])
            pids = [p for p in pids if p is not None]

            with conn.cursor() as cur:
                cur.execute("""
                    SELECT match_id, player_ref, AVG(implied_prob) AS p
                    FROM bookmaker_odds
                    WHERE match_id = ANY(%s)
                    GROUP BY match_id, player_ref
                """, (mids,))
                odds_by_mid: dict[int, dict[str, float]] = {}
                for r in cur.fetchall():
                    d = odds_by_mid.setdefault(r['match_id'], {})
                    d[r['player_ref']] = float(r['p']) if r['p'] is not None else None

            # RTT prefetch — only consulted when neutralise_rtt is False.
            rtt_by_pid: dict[int, dict] = {}
            if not getattr(self, 'neutralise_rtt', True) and pids:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT player_id, rtt_score, clay_rating, hard_rating,
                               grass_rating, indoor_rating, serve_rating,
                               return_rating, pressure_rating, form_score
                        FROM player_ratings
                        WHERE player_id = ANY(%s)
                    """, (pids,))
                    rtt_by_pid = {r['player_id']: dict(r) for r in cur.fetchall()}

            # Pre-build rank lookups for all players in a single query
            rank_by_pid: dict[int, tuple] = {}
            with conn.cursor() as cur:
                cur.execute("""
                    WITH names AS (
                        SELECT p.id AS pid,
                               COALESCE(NULLIF(TRIM(p.full_name), ''), p.name) AS name
                        FROM players p WHERE p.id = ANY(%s)
                    ),
                    tokens AS (
                        SELECT pid, name,
                               SPLIT_PART(REPLACE(name, '.', ''), ' ',
                                   array_length(string_to_array(REPLACE(name,'.',''),' '),1)
                               ) AS last_token
                        FROM names
                    ),
                    ranks AS (
                        SELECT
                            t.pid,
                            MIN(sm.winner_rank) FILTER (WHERE sm.winner_id = sp.player_id) AS rank_w,
                            MIN(sm.loser_rank)  FILTER (WHERE sm.loser_id  = sp.player_id) AS rank_l,
                            MAX(sm.winner_rank_points) FILTER (WHERE sm.winner_id = sp.player_id) AS pts_w,
                            MAX(sm.loser_rank_points)  FILTER (WHERE sm.loser_id  = sp.player_id) AS pts_l
                        FROM tokens t
                        JOIN sa_players sp ON sp.full_name ILIKE '%%' || t.last_token || '%%'
                        JOIN sa_matches sm ON (sm.winner_id = sp.player_id OR sm.loser_id = sp.player_id)
                        WHERE LENGTH(t.last_token) >= 3
                          AND sm.tourney_date >= CURRENT_DATE - INTERVAL '2 years'
                        GROUP BY t.pid
                    )
                    SELECT pid, COALESCE(rank_w, rank_l) AS rank, COALESCE(pts_w, pts_l) AS rank_pts
                    FROM ranks
                """, (pids,))
                for r in cur.fetchall():
                    rank_by_pid[r['pid']] = (r['rank'], r['rank_pts'])
        finally:
            conn.close()

        log.info(f"Predicting {len(upcoming)} upcoming matches "
                 f"(prefetched odds for {len(odds_by_mid)} matches, "
                 f"ranks for {len(rank_by_pid)} players)...")
        predicted = 0

        # Stash prefetches on self so predict_match can use them via the
        # _odds_by_mid / _rtt_by_pid hooks (predict_match falls back to
        # SQL if a cache isn't populated).
        self._odds_by_mid = odds_by_mid
        self._rtt_by_pid = rtt_by_pid if rtt_by_pid else None
        # Persistent write connection — eliminates per-match reconnect.
        self._write_conn = psycopg2.connect(self.db_url)

        for match in upcoming:
            try:
                level = self._tour_category_to_level(
                    match.get('tour_category'), match.get('type_name')
                )
                event_date = match.get('event_date')
                p1_rank, p1_rank_pts = rank_by_pid.get(match['first_player_id'], (None, None))
                p2_rank, p2_rank_pts = rank_by_pid.get(match['second_player_id'], (None, None))
                pred = self.predict_match(
                    match_id     = match['match_id'],
                    p1_id        = match['first_player_id'],
                    p2_id        = match['second_player_id'],
                    surface      = match.get('surface'),
                    tourney_level = level,
                    round_       = match.get('round', 'R32') or 'R32',
                    best_of      = match.get('best_of', 3) or 3,
                    p1_rank      = p1_rank,
                    p2_rank      = p2_rank,
                    p1_rank_pts  = p1_rank_pts,
                    p2_rank_pts  = p2_rank_pts,
                    p1_age       = self._age_at(match.get('p1_birthday'), event_date),
                    p2_age       = self._age_at(match.get('p2_birthday'), event_date),
                    p1_ht        = match.get('p1_ht'),
                    p2_ht        = match.get('p2_ht'),
                    p1_hand      = match.get('p1_hand'),
                    p2_hand      = match.get('p2_hand'),
                    match_date   = event_date,
                )
                self.write_prediction(pred)
                self._write_conn.commit()  # commit per row so partial runs persist
                predicted += 1
            except Exception as e:
                log.warning(f"  Failed match {match['match_id']}: {e}")

        try:
            self._write_conn.commit()
            self._write_conn.close()
        except Exception:
            pass
        self._write_conn = None
        log.info(f"  Predicted {predicted}/{len(upcoming)} matches")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--match-id',  type=int)
    parser.add_argument('--today',     action='store_true')
    parser.add_argument('--upcoming',  type=int, default=1)
    parser.add_argument('--years-back', type=int, default=8,
                        help='Limit Elo training data to last N years (default 8). '
                             'None / 0 = full history.')
    parser.add_argument('--use-rtt', action='store_true',
                        help='Read player_ratings instead of neutralising RTT '
                             'features. Only enable after running ml.ratings on '
                             'the corrected match data.')
    parser.add_argument('--skip-existing', action='store_true',
                        help='Skip matches that already have a prediction at '
                             'the current MODEL_VERSION. Useful for resuming '
                             'a long run.')
    parser.add_argument('--no-model', action='store_true',
                        help='Skip loading the trained logistic / xgboost / '
                             'lightgbm models — predictions use pure surface '
                             'Elo. Roughly 10× faster, and the trained models '
                             'are currently miscalibrated for the corrected '
                             'name-keyed feature distribution anyway.')
    args = parser.parse_args()

    predictor = LivePredictor(neutralise_rtt=not args.use_rtt)
    if not args.no_model:
        predictor.load_models()
    yb = args.years_back if args.years_back and args.years_back > 0 else None
    predictor.load_player_history(years_back=yb)

    if args.today or args.upcoming:
        predictor.predict_upcoming(days_ahead=args.upcoming,
                                   skip_existing=args.skip_existing)


if __name__ == '__main__':
    main()
