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
MODEL_VERSION = "v1"

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

    def __init__(self, db_url: str = DB_URL):
        self.db_url = db_url
        self._models: dict[str, object] = {}
        self._elo_engine = None
        self._player_window = None
        self._h2h_tracker = None

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

    def load_player_history(self) -> "LivePredictor":
        """
        Load historical match data (both sa_matches and live matches) to
        build Elo ratings and rolling stats for all active players.
        """
        from ml.elo import EloEngine, SURFACE_MAP
        from ml.features import PlayerWindow, H2HTracker, safe_pct

        log.info("Building player history from sa_matches + live matches ...")

        conn = psycopg2.connect(self.db_url)
        conn.cursor_factory = psycopg2.extras.RealDictCursor

        try:
            # Load from sa_matches (historical)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        winner_id, loser_id, tourney_date, surface, tourney_level,
                        tour, match_num, score,
                        w_svpt, w_1st_won, w_2nd_won, w_sv_gms, w_ace, w_df,
                        w_bp_saved, w_bp_faced, w_bp_save_pct,
                        l_svpt, l_1st_won, l_2nd_won, l_sv_gms, l_ace, l_df,
                        l_bp_saved, l_bp_faced, l_bp_save_pct
                    FROM sa_matches
                    WHERE tourney_date IS NOT NULL
                      AND winner_id IS NOT NULL
                      AND loser_id IS NOT NULL
                    ORDER BY tourney_date, match_num
                """)
                sa_rows = cur.fetchall()

            # Load from live matches table (join to get real surface)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        m.first_player_id  AS winner_id,
                        m.second_player_id AS loser_id,
                        m.event_date       AS tourney_date,
                        s.name             AS surface,
                        NULL               AS tourney_level,
                        'ATP'              AS tour,
                        0                  AS match_num,
                        m.final_result     AS score
                    FROM matches m
                    LEFT JOIN tournaments t ON t.id = m.tournament_id
                    LEFT JOIN surfaces s    ON s.id = t.surface_id
                    WHERE m.event_status = 'Finished'
                      AND m.winner = 'First Player'
                      AND m.first_player_id IS NOT NULL
                      AND m.second_player_id IS NOT NULL
                    UNION ALL
                    SELECT
                        m.second_player_id AS winner_id,
                        m.first_player_id  AS loser_id,
                        m.event_date       AS tourney_date,
                        s.name             AS surface,
                        NULL               AS tourney_level,
                        'ATP'              AS tour,
                        0                  AS match_num,
                        m.final_result     AS score
                    FROM matches m
                    LEFT JOIN tournaments t ON t.id = m.tournament_id
                    LEFT JOIN surfaces s    ON s.id = t.surface_id
                    WHERE m.event_status = 'Finished'
                      AND m.winner = 'Second Player'
                      AND m.first_player_id IS NOT NULL
                      AND m.second_player_id IS NOT NULL
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

        log.info(f"  {len(df_hist):,} historical matches loaded")

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

            self._player_window.update(w_id, won=True,  surface=surface, match_date=date,
                                       svpt_won=w_svpt_won, ret_won=w_ret_won,
                                       ace_rate=safe_pct(row.get('w_ace'), row.get('w_sv_gms')),
                                       df_rate=safe_pct(row.get('w_df'), row.get('w_sv_gms')),
                                       bp_save=row.get('w_bp_save_pct'),
                                       bp_conv=w_bp_conv)
            self._player_window.update(l_id, won=False, surface=surface, match_date=date,
                                       svpt_won=l_svpt_won, ret_won=l_ret_won,
                                       ace_rate=safe_pct(row.get('l_ace'), row.get('l_sv_gms')),
                                       df_rate=safe_pct(row.get('l_df'), row.get('l_sv_gms')),
                                       bp_save=row.get('l_bp_save_pct'),
                                       bp_conv=l_bp_conv)
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

        # ── Elo features
        p1_elo = self._elo_engine.player_elo(p1_id)
        p2_elo = self._elo_engine.player_elo(p2_id)
        p1_elo_overall = p1_elo['overall']
        p2_elo_overall = p2_elo['overall']
        p1_surf_elo = p1_elo.get(f'elo_{surf_key}') if surf_key else None
        p2_surf_elo = p2_elo.get(f'elo_{surf_key}') if surf_key else None

        from ml.elo import expected_score
        elo_win_prob      = expected_score(p1_elo_overall, p2_elo_overall)
        surf_elo_win_prob = expected_score(p1_surf_elo, p2_surf_elo) if surf_key else None

        # ── Rolling stats
        p1_w = self._player_window.get_stats(p1_id, surface, [10, 20, 50])
        p2_w = self._player_window.get_stats(p2_id, surface, [10, 20, 50])
        p1_days = self._player_window.days_since_last(p1_id, match_date)
        p2_days = self._player_window.days_since_last(p2_id, match_date)

        # ── H2H
        h2h_f = self._h2h_tracker.get(p1_id, p2_id, surface)

        # ── RTT ratings from player_ratings table
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
        try:
            _bk_conn = psycopg2.connect(self.db_url)
            _bk_conn.cursor_factory = psycopg2.extras.RealDictCursor
            with _bk_conn.cursor() as cur:
                cur.execute("""
                    SELECT odd_first_player, odd_second_player
                    FROM bookmaker_odds
                    WHERE match_id = %s
                    ORDER BY fetched_at DESC
                    LIMIT 1
                """, (match_id,))
                odds_row = cur.fetchone()
            _bk_conn.close()
            if odds_row and odds_row['odd_first_player'] and odds_row['odd_second_player']:
                o1 = float(odds_row['odd_first_player'])
                o2 = float(odds_row['odd_second_player'])
                # Convert decimal odds to implied probability (no-vig)
                raw1 = 1.0 / o1
                raw2 = 1.0 / o2
                total = raw1 + raw2
                features['market_impl_p1'] = raw1 / total if total > 0 else 0.5
            else:
                features['market_impl_p1'] = 0.5
        except Exception:
            features['market_impl_p1'] = 0.5

        # ── Model prediction (fall back to Elo if no model loaded)
        model_key = 'elo_fallback'
        if self._models:
            try:
                model, model_key = self._get_model(surface)
                feat_names = _get_model_feature_names(model)
                if not feat_names:
                    from ml.train import CORE_FEATURES
                    feat_names = CORE_FEATURES
                X = pd.DataFrame([{k: features.get(k) for k in feat_names}])
                prob_p1 = float(model.predict_proba(X)[0, 1])
            except Exception as e:
                log.debug(f"Model prediction failed ({e}), falling back to Elo")
                prob_p1 = surf_elo_win_prob if surf_elo_win_prob is not None else elo_win_prob
                model_key = 'elo_fallback'
        else:
            # No models loaded — use surface Elo as best available estimate
            prob_p1 = surf_elo_win_prob if surf_elo_win_prob is not None else elo_win_prob
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
        """Write a single prediction to the model_predictions table."""
        conn = psycopg2.connect(self.db_url)
        try:
            with conn.cursor() as cur:
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
            conn.commit()
        finally:
            conn.close()

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

    def predict_upcoming(self, days_ahead: int = 1):
        """Predict all upcoming matches in the production matches table."""
        conn = psycopg2.connect(self.db_url)
        conn.cursor_factory = psycopg2.extras.RealDictCursor
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)

        try:
            with conn.cursor() as cur:
                cur.execute("""
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
                """, (str(today), str(cutoff)))
                upcoming = cur.fetchall()
        finally:
            conn.close()

        log.info(f"Predicting {len(upcoming)} upcoming matches ...")
        predicted = 0

        # Open a persistent connection for rank lookups (avoids per-match reconnect)
        conn_ranks = psycopg2.connect(self.db_url)

        for match in upcoming:
            try:
                level = self._tour_category_to_level(
                    match.get('tour_category'), match.get('type_name')
                )
                event_date = match.get('event_date')
                p1_rank, p1_rank_pts = self._lookup_rank(
                    match['first_player_id'], conn_ranks
                )
                p2_rank, p2_rank_pts = self._lookup_rank(
                    match['second_player_id'], conn_ranks
                )
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
                predicted += 1
            except Exception as e:
                log.warning(f"  Failed match {match['match_id']}: {e}")

        conn_ranks.close()
        log.info(f"  Predicted {predicted}/{len(upcoming)} matches")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--match-id',  type=int)
    parser.add_argument('--today',     action='store_true')
    parser.add_argument('--upcoming',  type=int, default=1)
    args = parser.parse_args()

    predictor = LivePredictor()
    predictor.load_models()
    predictor.load_player_history()

    if args.today or args.upcoming:
        predictor.predict_upcoming(days_ahead=args.upcoming)


if __name__ == '__main__':
    main()
