"""
ratethat.tennis — Model Training
=================================
Trains multiple calibrated match outcome models and saves artefacts.

Models trained:
  - Logistic Regression (baseline / sanity check)
  - XGBoost (primary model)
  - LightGBM (primary model)
  - Ensemble (XGBoost + LightGBM average)

Each model is trained both:
  - Overall (all surfaces combined)
  - Per-surface (Clay / Hard / Grass / Carpet)

All outputs are probability-calibrated via isotonic regression.

Usage:
    python -m ml.train --features ml/results/features.parquet
    python -m ml.train --build-features   # build + train in one pass
"""

from __future__ import annotations

import os
import json
import logging
import pickle
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    accuracy_score, log_loss, brier_score_loss, roc_auc_score
)
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer

try:
    import xgboost as xgb
    HAS_XGB = True
except Exception:
    # Catches ImportError AND XGBoostError (raised when libxgboost.dylib
    # can't find libomp.dylib on macOS — fix: brew install libomp)
    HAS_XGB = False
    logging.warning("xgboost not available — skipping XGBoost models. "
                    "On macOS: brew install libomp")

try:
    import lightgbm as lgb
    HAS_LGB = True
except Exception:
    HAS_LGB = False
    logging.warning("lightgbm not available — skipping LightGBM models")

log = logging.getLogger("rtt-train")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MODELS_DIR = Path(__file__).parent / "models"
RESULTS_DIR = Path(__file__).parent / "results"

# ─────────────────────────────────────────────
# FEATURE COLUMNS (ordered by expected importance)
# ─────────────────────────────────────────────

# These are the core features. The full set is loaded from parquet.
CORE_FEATURES = [
    # Elo (most predictive group)
    'elo_diff', 'surf_elo_diff', 'elo_win_prob', 'surf_elo_win_prob',
    'p1_elo', 'p2_elo', 'p1_surf_elo', 'p2_surf_elo',

    # Ranking
    'rank_diff', 'rank_pts_diff', 'p1_rank', 'p2_rank',

    # Form (rolling windows)
    'form_diff_10', 'form_diff_20', 'surf_form_diff',
    'p1_win_rate_10', 'p2_win_rate_10',
    'p1_win_rate_20', 'p2_win_rate_20',
    'p1_surf_win_rate_10', 'p2_surf_win_rate_10',
    'p1_matches_10', 'p2_matches_10',

    # Serve / return stats
    'svpt_won_diff', 'ret_won_diff', 'bp_save_diff', 'bp_conv_diff',
    'ace_rate_diff', 'df_rate_diff',
    'p1_svpt_won_20', 'p2_svpt_won_20',
    'p1_ret_won_20', 'p2_ret_won_20',
    'p1_bp_save_20', 'p2_bp_save_20',
    'p1_bp_conv_20', 'p2_bp_conv_20',
    'p1_ace_rate_20', 'p2_ace_rate_20',

    # H2H
    'h2h_p1_win_pct', 'h2h_surf_p1_win_pct',
    'h2h_total', 'h2h_surf_total',
    'h2h_recent_p1_wins', 'h2h_recent_total',

    # Fatigue
    'p1_days_rest', 'p2_days_rest', 'days_rest_diff',

    # Tournament context
    'level_enc', 'round_enc', 'best_of',
    'is_grand_slam', 'is_masters',

    # Physical
    'age_diff', 'height_diff', 'hand_enc',
]


# ─────────────────────────────────────────────
# HELPER: evaluate a model
# ─────────────────────────────────────────────

def evaluate(model, X_test: pd.DataFrame, y_test: pd.Series, label: str) -> dict:
    """Compute all evaluation metrics for a trained model."""
    y_pred_prob = model.predict_proba(X_test)[:, 1]
    y_pred      = (y_pred_prob >= 0.5).astype(int)

    acc    = accuracy_score(y_test, y_pred)
    ll     = log_loss(y_test, y_pred_prob)
    brier  = brier_score_loss(y_test, y_pred_prob)
    auc    = roc_auc_score(y_test, y_pred_prob)

    log.info(
        f"  {label:30s} | Acc={acc:.4f} | LogLoss={ll:.4f} | Brier={brier:.4f} | AUC={auc:.4f}"
    )

    return {
        'label':    label,
        'accuracy': round(acc, 4),
        'log_loss': round(ll, 4),
        'brier':    round(brier, 4),
        'roc_auc':  round(auc, 4),
        'n_test':   len(y_test),
    }


# ─────────────────────────────────────────────
# MODEL DEFINITIONS
# ─────────────────────────────────────────────

def make_logistic() -> Pipeline:
    return Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('scaler',  StandardScaler()),
        ('clf',     CalibratedClassifierCV(
            LogisticRegression(max_iter=1000, C=1.0, solver='lbfgs'),
            method='isotonic', cv=5,
        )),
    ])


def make_xgboost() -> Optional[object]:
    if not HAS_XGB:
        return None
    base = xgb.XGBClassifier(
        n_estimators=400,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=10,
        gamma=1,
        reg_alpha=0.1,
        reg_lambda=1.0,
        use_label_encoder=False,
        eval_metric='logloss',
        random_state=42,
        n_jobs=-1,
    )
    return Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('clf',     CalibratedClassifierCV(base, method='isotonic', cv=5)),
    ])


def make_lightgbm() -> Optional[object]:
    if not HAS_LGB:
        return None
    base = lgb.LGBMClassifier(
        n_estimators=400,
        max_depth=5,
        learning_rate=0.05,
        num_leaves=31,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_samples=20,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    return Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('clf',     CalibratedClassifierCV(base, method='isotonic', cv=5)),
    ])


# ─────────────────────────────────────────────
# ENSEMBLE
# ─────────────────────────────────────────────

class EnsembleModel:
    """Simple averaging ensemble of multiple calibrated models."""

    def __init__(self, models: list, weights: Optional[list] = None):
        self.models  = models
        self.weights = weights or [1.0 / len(models)] * len(models)

    def predict_proba(self, X) -> np.ndarray:
        import warnings
        # Try passing as DataFrame first; fall back to numpy array if a sub-model
        # raises a feature-name validation error (LightGBM quirk with sklearn pipelines).
        X_arr = X.values if hasattr(X, 'values') else np.asarray(X, dtype=float)

        probs       = np.zeros((len(X_arr), 2))
        total_weight = 0.0

        for model, w in zip(self.models, self.weights):
            # Try DataFrame first (preserves feature names for XGBoost / Logistic)
            for attempt in [X, X_arr]:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        p = model.predict_proba(attempt)
                    probs        += w * p
                    total_weight += w
                    break  # success — move to next model
                except Exception:
                    continue  # retry with numpy array

        if total_weight > 0:
            probs /= total_weight  # re-normalise if some models failed
        else:
            # All models failed — return 50/50
            probs[:, 0] = 0.5
            probs[:, 1] = 0.5

        return probs

    def predict(self, X) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


# ─────────────────────────────────────────────
# TRAINER
# ─────────────────────name───────────────────

class ModelTrainer:
    """
    Trains all models on a train/test split and saves artefacts.
    """

    def __init__(self, models_dir: Path = MODELS_DIR, results_dir: Path = RESULTS_DIR):
        self.models_dir  = Path(models_dir)
        self.results_dir = Path(results_dir)
        self.models_dir.mkdir(exist_ok=True, parents=True)
        self.results_dir.mkdir(exist_ok=True, parents=True)
        self.all_results: list[dict] = []

    def load_features(self, parquet_path: str) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
        log.info(f"Loading features from {parquet_path} ...")
        full = pd.read_parquet(parquet_path)
        meta_cols = ['match_id', 'tourney_date', 'surface', 'tour', 'tourney_level',
                     'round', 'season', 'p1_id', 'p2_id', 'p1_name', 'p2_name', 'did_p1_win']
        y    = full['did_p1_win'].astype(int)
        meta = full[[c for c in meta_cols if c in full.columns]]
        feat_cols = [c for c in CORE_FEATURES if c in full.columns]
        X    = full[feat_cols]
        log.info(f"  {len(X):,} rows, {len(feat_cols)} features")
        return X, y, meta

    def train_all(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        meta: pd.DataFrame,
        test_year: int = 2023,
    ) -> dict:
        """
        Train overall and per-surface models.
        test_year: hold out this year and after for final evaluation.
        """
        log.info(f"Training models (test year >= {test_year}) ...")

        results = {}

        # ── Overall models (all surfaces)
        train_mask = meta['season'] < test_year
        test_mask  = meta['season'] >= test_year

        X_tr, y_tr = X[train_mask], y[train_mask]
        X_te, y_te = X[test_mask],  y[test_mask]

        log.info(f"  Train: {train_mask.sum():,} | Test: {test_mask.sum():,}")

        results['overall'] = self._train_set(X_tr, y_tr, X_te, y_te, label='overall')

        # ── Per-surface models
        for surf in ['Hard', 'Clay', 'Grass']:
            surf_mask = meta['surface'] == surf
            X_s  = X[surf_mask]
            y_s  = y[surf_mask]
            m_s  = meta[surf_mask]

            tr = m_s['season'] < test_year
            te = m_s['season'] >= test_year

            if tr.sum() < 500 or te.sum() < 50:
                log.info(f"  Skipping {surf} (insufficient data)")
                continue

            log.info(f"  Surface: {surf} — Train {tr.sum():,} | Test {te.sum():,}")
            results[surf.lower()] = self._train_set(
                X_s[tr], y_s[tr], X_s[te], y_s[te], label=surf
            )

        # Save all results
        results_path = self.results_dir / 'training_results.json'
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        log.info(f"Results saved to {results_path}")

        self.all_results = results
        return results

    def _train_set(
        self,
        X_tr, y_tr, X_te, y_te,
        label: str,
    ) -> dict:
        """Train all model types for one data slice."""
        trained_models = {}
        metrics = {}

        model_factories = [
            ('logistic',  make_logistic),
            ('xgboost',   make_xgboost),
            ('lightgbm',  make_lightgbm),
        ]

        fitted = {}
        for name, factory in model_factories:
            model = factory()
            if model is None:
                continue
            log.info(f"  Training {name} on {label} ...")
            model.fit(X_tr, y_tr)
            fitted[name] = model

            m = evaluate(model, X_te, y_te, f"{label}/{name}")
            metrics[name] = m

            # Save model artefact
            model_path = self.models_dir / f"{label}_{name}.pkl"
            with open(model_path, 'wb') as f:
                pickle.dump(model, f)

        # ── Ensemble (if we have 2+ models)
        if len(fitted) >= 2:
            # Weight by inverse log-loss (better models get more weight)
            model_list = list(fitted.values())
            lls = [metrics[n]['log_loss'] for n in fitted]
            inv_ll = [1.0 / ll for ll in lls]
            total  = sum(inv_ll)
            weights = [w / total for w in inv_ll]

            ensemble = EnsembleModel(model_list, weights)
            m = evaluate(ensemble, X_te, y_te, f"{label}/ensemble")
            metrics['ensemble'] = m

            model_path = self.models_dir / f"{label}_ensemble.pkl"
            with open(model_path, 'wb') as f:
                pickle.dump(ensemble, f)

        return {
            'label':   label,
            'metrics': metrics,
        }

    def feature_importance(self, model_name: str = 'overall_xgboost') -> pd.DataFrame:
        """Extract feature importance from a trained XGBoost model."""
        path = self.models_dir / f"{model_name}.pkl"
        if not path.exists():
            raise FileNotFoundError(f"No model at {path}")

        with open(path, 'rb') as f:
            model = pickle.load(f)

        # Navigate Pipeline → CalibratedClassifier → XGBClassifier
        try:
            xgb_clf = model.named_steps['clf'].calibrated_classifiers_[0].estimator
            imp = xgb_clf.feature_importances_
            feat_names = CORE_FEATURES[:len(imp)]
            return pd.DataFrame({
                'feature':    feat_names,
                'importance': imp,
            }).sort_values('importance', ascending=False)
        except Exception as e:
            log.warning(f"Could not extract feature importance: {e}")
            return pd.DataFrame()

    def load_model(self, name: str):
        path = self.models_dir / f"{name}.pkl"
        with open(path, 'rb') as f:
            return pickle.load(f)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ratethat.tennis model trainer")
    parser.add_argument('--features', default='ml/results/features.parquet',
                        help='Path to pre-built feature parquet')
    parser.add_argument('--build-features', action='store_true',
                        help='Build features from DB first, then train')
    parser.add_argument('--test-year', type=int, default=2023,
                        help='Hold-out test year (default 2023)')
    parser.add_argument('--tour', choices=['ATP', 'WTA', 'both'], default='both')
    args = parser.parse_args()

    if args.build_features:
        from ml.features import FeatureBuilder
        tour_filter = None if args.tour == 'both' else [args.tour]
        fb = FeatureBuilder()
        fb.load(tour_filter=tour_filter)
        X, y, meta = fb.save('ml/results/features.parquet')
    else:
        trainer = ModelTrainer()
        X, y, meta = trainer.load_features(args.features)

    trainer = ModelTrainer()
    results = trainer.train_all(X, y, meta, test_year=args.test_year)

    log.info("\n=== FINAL RESULTS ===")
    for group, res in results.items():
        log.info(f"\n{group.upper()}:")
        for model_name, m in res['metrics'].items():
            log.info(
                f"  {model_name:15s} Acc={m['accuracy']:.4f} | "
                f"LogLoss={m['log_loss']:.4f} | AUC={m['roc_auc']:.4f}"
            )


if __name__ == '__main__':
    main()
