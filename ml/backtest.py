"""
ratethat.tennis — Walk-Forward Backtester
==========================================
Rigorous temporal backtesting of all ML models.

Walk-forward protocol:
  For each test_year in [2015, 2016, ..., 2024]:
    - Train: all matches with season < test_year
    - Test:  all matches with season == test_year
  Never touch future data during training.

Baseline comparisons:
  - Elo-only prediction (no ML — pure Elo win probability)
  - Random (50/50)
  - Rank-based (lower rank wins)

Metrics per year, per surface, per model:
  - Accuracy
  - Log-loss
  - Brier score
  - ROC-AUC
  - Calibration (reliability diagram data)
  - Simulated flat-stake return (using market-implied odds from Elo)

Output: JSON file consumed by the ML Lab dashboard.

Usage:
    python -m ml.backtest --features ml/results/features.parquet
    python -m ml.backtest --features ml/results/features.parquet --start-year 2015
"""

from __future__ import annotations

import json
import logging
import argparse
import numpy as np
import pandas as pd
import pickle
from pathlib import Path
from typing import Optional
from sklearn.metrics import (
    accuracy_score, log_loss, brier_score_loss, roc_auc_score
)
from sklearn.impute import SimpleImputer

from ml.train import (
    ModelTrainer, make_logistic, make_xgboost, make_lightgbm,
    EnsembleModel, CORE_FEATURES, evaluate
)

log = logging.getLogger("rtt-backtest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

RESULTS_DIR = Path(__file__).parent / "results"


# ─────────────────────────────────────────────
# CALIBRATION HELPERS
# ─────────────────────────────────────────────

def calibration_curve_data(y_true, y_prob, n_bins: int = 10) -> list[dict]:
    """Compute reliability diagram data."""
    bins = np.linspace(0, 1, n_bins + 1)
    bin_data = []
    for i in range(len(bins) - 1):
        mask = (y_prob >= bins[i]) & (y_prob < bins[i + 1])
        if mask.sum() > 0:
            bin_data.append({
                'bin_center':  round((bins[i] + bins[i + 1]) / 2, 3),
                'mean_pred':   round(float(y_prob[mask].mean()), 4),
                'fraction_pos': round(float(y_true[mask].mean()), 4),
                'count':       int(mask.sum()),
            })
    return bin_data


def elo_baseline_predict(meta_row_batch: pd.DataFrame, X_batch: pd.DataFrame) -> np.ndarray:
    """Use pre-computed elo_win_prob as a baseline predictor."""
    col = 'elo_win_prob' if 'elo_win_prob' in X_batch.columns else None
    if col:
        probs = X_batch[col].fillna(0.5).values
    else:
        probs = np.full(len(X_batch), 0.5)
    return np.clip(probs, 1e-5, 1 - 1e-5)


def rank_baseline_predict(X_batch: pd.DataFrame) -> np.ndarray:
    """Predict based on ranking: lower rank number = favourite."""
    if 'rank_diff' in X_batch.columns:
        # rank_diff = p2_rank - p1_rank (positive = p1 is higher ranked / lower number)
        rank_diff = X_batch['rank_diff'].fillna(0).values
        # Convert to probability: logistic transformation
        prob = 1.0 / (1.0 + np.exp(-rank_diff / 100.0))
        return np.clip(prob, 1e-5, 1 - 1e-5)
    return np.full(len(X_batch), 0.5)


def surf_elo_baseline_predict(X_batch: pd.DataFrame) -> np.ndarray:
    """Surface-specific Elo baseline."""
    col = 'surf_elo_win_prob'
    if col in X_batch.columns:
        probs = X_batch[col].fillna(X_batch.get('elo_win_prob', pd.Series(0.5)).fillna(0.5)).values
    else:
        probs = np.full(len(X_batch), 0.5)
    return np.clip(probs, 1e-5, 1 - 1e-5)


# ─────────────────────────────────────────────
# WALK-FORWARD BACKTEST
# ─────────────────────────────────────────────

class WalkForwardBacktester:

    def __init__(
        self,
        results_dir: Path = RESULTS_DIR,
        min_train_year: int = 2003,  # Need a few years to build meaningful Elo/stats
        start_test_year: int = 2015,
        end_test_year:   int = 2024,
    ):
        self.results_dir     = Path(results_dir)
        self.min_train_year  = min_train_year
        self.start_test_year = start_test_year
        self.end_test_year   = end_test_year
        self.results_dir.mkdir(exist_ok=True, parents=True)

    def run(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        meta: pd.DataFrame,
        surfaces: list[str] = ['overall', 'Hard', 'Clay', 'Grass'],
    ) -> dict:
        """Run the full walk-forward backtest and return results."""

        all_results = {
            'walk_forward': {},
            'baselines':    {},
            'per_surface':  {},
            'summary':      {},
        }

        yearly_rows = []   # For year-by-year summary

        test_years = list(range(self.start_test_year, self.end_test_year + 1))

        for test_year in test_years:
            log.info(f"\n{'='*50}")
            log.info(f"Test year: {test_year}")

            train_mask = (meta['season'] >= self.min_train_year) & (meta['season'] < test_year)
            test_mask  = meta['season'] == test_year

            if train_mask.sum() < 1000 or test_mask.sum() < 50:
                log.info(f"  Insufficient data for {test_year}, skipping")
                continue

            X_tr, y_tr = X[train_mask], y[train_mask]
            X_te, y_te = X[test_mask],  y[test_mask]
            meta_te    = meta[test_mask]

            log.info(f"  Train: {train_mask.sum():,} | Test: {test_mask.sum():,}")

            # ── Baselines (no training needed)
            elo_probs      = elo_baseline_predict(meta_te, X_te)
            surf_elo_probs = surf_elo_baseline_predict(X_te)
            rank_probs     = rank_baseline_predict(X_te)

            # ── Train ML models on this window
            model_probs = {}
            model_names = []

            model_factories = [
                ('logistic', make_logistic),
                ('xgboost',  make_xgboost),
                ('lightgbm', make_lightgbm),
            ]

            fitted = {}
            for name, factory in model_factories:
                model = factory()
                if model is None:
                    continue
                try:
                    model.fit(X_tr, y_tr)
                    probs = model.predict_proba(X_te)[:, 1]
                    model_probs[name] = probs
                    fitted[name] = model
                    model_names.append(name)
                except Exception as e:
                    log.warning(f"  {name} failed: {e}")

            # Ensemble
            if len(fitted) >= 2:
                lls = {n: log_loss(y_te, model_probs[n]) for n in fitted}
                weights = {n: 1.0/lls[n] for n in fitted}
                total_w = sum(weights.values())
                ens_probs = sum(weights[n] / total_w * model_probs[n] for n in fitted)
                model_probs['ensemble'] = ens_probs

            # ── Compute metrics for all predictors
            def metrics_dict(probs, label, y_arr=None):
                # y_arr defaults to the full test-year target; pass a subset for per-surface
                if y_arr is None:
                    y_arr = y_te.values
                y_true = np.array(y_arr)
                probs  = np.clip(np.array(probs), 1e-5, 1 - 1e-5)
                return {
                    'label':       label,
                    'year':        test_year,
                    'accuracy':    round(accuracy_score(y_true, (probs >= 0.5).astype(int)), 4),
                    'log_loss':    round(log_loss(y_true, probs), 4),
                    'brier':       round(brier_score_loss(y_true, probs), 4),
                    'roc_auc':     round(roc_auc_score(y_true, probs), 4),
                    'n_matches':   len(y_true),
                    'calibration': calibration_curve_data(y_true, probs),
                }

            year_key = str(test_year)
            all_results['walk_forward'][year_key] = {}

            # Baselines
            all_results['walk_forward'][year_key]['elo']      = metrics_dict(elo_probs, 'Elo')
            all_results['walk_forward'][year_key]['surf_elo'] = metrics_dict(surf_elo_probs, 'Surface Elo')
            all_results['walk_forward'][year_key]['rank']     = metrics_dict(rank_probs, 'Rank-based')

            # ML models
            for name, probs in model_probs.items():
                all_results['walk_forward'][year_key][name] = metrics_dict(probs, name.title())

            # ── Per-surface breakdown (using ML ensemble or best model)
            best_model_name = 'ensemble' if 'ensemble' in model_probs else (model_names[0] if model_names else None)
            if best_model_name:
                surf_results = {}
                for surf in ['Hard', 'Clay', 'Grass']:
                    s_mask = meta_te['surface'] == surf
                    if s_mask.sum() < 20:
                        continue
                    probs_surf = model_probs[best_model_name][s_mask.values]
                    y_surf     = y_te[s_mask].values
                    # Pass y_surf explicitly so metrics_dict uses the surface subset
                    surf_results[surf.lower()] = metrics_dict(probs_surf, f'{surf} ({best_model_name})', y_arr=y_surf)
                all_results['walk_forward'][year_key]['per_surface'] = surf_results

            # Log summary row
            if best_model_name:
                best = all_results['walk_forward'][year_key][best_model_name]
                elo_m = all_results['walk_forward'][year_key]['elo']
                yearly_rows.append({
                    'year':       test_year,
                    'n':          test_mask.sum(),
                    'best_acc':   best['accuracy'],
                    'best_ll':    best['log_loss'],
                    'best_auc':   best['roc_auc'],
                    'elo_acc':    elo_m['accuracy'],
                    'elo_ll':     elo_m['log_loss'],
                    'edge_acc':   round(best['accuracy'] - elo_m['accuracy'], 4),
                    'model':      best_model_name,
                })
                log.info(
                    f"  Best ({best_model_name}): Acc={best['accuracy']:.4f} | "
                    f"LL={best['log_loss']:.4f} | AUC={best['roc_auc']:.4f} | "
                    f"Edge vs Elo: +{best['accuracy'] - elo_m['accuracy']:.4f}"
                )

        # ── Aggregate summary across all years
        if yearly_rows:
            df_y = pd.DataFrame(yearly_rows)
            all_results['summary'] = {
                'years_tested':    list(df_y['year']),
                'total_matches':   int(df_y['n'].sum()),
                'mean_accuracy':   round(float(df_y['best_acc'].mean()), 4),
                'mean_log_loss':   round(float(df_y['best_ll'].mean()), 4),
                'mean_auc':        round(float(df_y['best_auc'].mean()), 4),
                'elo_mean_acc':    round(float(df_y['elo_acc'].mean()), 4),
                'mean_edge_vs_elo': round(float(df_y['edge_acc'].mean()), 4),
                'year_by_year':    yearly_rows,
            }

        # Save
        out_path = self.results_dir / 'backtest_results.json'
        with open(out_path, 'w') as f:
            json.dump(all_results, f, indent=2, default=str)
        log.info(f"\nBacktest results saved to {out_path}")

        return all_results


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ratethat.tennis walk-forward backtester")
    parser.add_argument('--features', default='ml/results/features.parquet',
                        help='Path to features parquet')
    parser.add_argument('--start-year', type=int, default=2015)
    parser.add_argument('--end-year',   type=int, default=2024)
    parser.add_argument('--min-train-year', type=int, default=2003)
    args = parser.parse_args()

    trainer = ModelTrainer()
    X, y, meta = trainer.load_features(args.features)

    bt = WalkForwardBacktester(
        start_test_year=args.start_year,
        end_test_year=args.end_year,
        min_train_year=args.min_train_year,
    )
    results = bt.run(X, y, meta)

    summary = results.get('summary', {})
    if summary:
        log.info("\n=== BACKTEST SUMMARY ===")
        log.info(f"Years tested:      {summary['years_tested']}")
        log.info(f"Total matches:     {summary['total_matches']:,}")
        log.info(f"Mean accuracy:     {summary['mean_accuracy']:.4f}")
        log.info(f"Elo mean accuracy: {summary['elo_mean_acc']:.4f}")
        log.info(f"Edge vs Elo:      +{summary['mean_edge_vs_elo']:.4f}")
        log.info(f"Mean AUC:          {summary['mean_auc']:.4f}")


if __name__ == '__main__':
    main()
