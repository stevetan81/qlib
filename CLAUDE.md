# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Role

资深量化模型研究员。使用 Qlib workflow 研究优化 A 股短线波段策略（持股 1-10 天），最大化收益。

## Project Context

This is a fork of [Microsoft Qlib](https://github.com/microsoft/qlib) with a research overlay (`hats_workflows/`) for HATS A-share swing trading. HATS architecture is split across repos:
- **Data collection** — HATS project (`/home/tanlu/myworkspace/HATS/`)
- **Qlib quantitative research** — this workspace (`/home/tanlu/myworkspace/qlib/`)
- **LLM analysis** — HATS project

## Build & Development Commands

```bash
# Install Qlib (editable) with Cython extensions
make install                    # = make prerequisite + make dependencies

# Install with all extras (dev, lint, test, etc.)
make dev

# Run specific test
pytest tests/test_workflow.py
pytest tests/test_all_pipeline.py -m "not slow"

# Lint (runs black, pylint, flake8, mypy, nbqa)
make lint
# Individual linters:
make black    # black . -l 120 --check --diff
make pylint
make flake8   # --ignore=E501,F541,E266,E402,W503,E731,E203
make mypy

# Build wheel
make build
```

## Critical Constraints

- **All Rolling experiments MUST run from `/tmp`** to avoid qlib source import conflicts:
  ```bash
  cd /tmp && python /home/tanlu/myworkspace/qlib/hats_workflows/rolling_benchmark.py \
    --conf_path=/home/tanlu/myworkspace/qlib/hats_workflows/workflow_config_rolling_double_ensemble_dyn.yaml \
    --horizon=5 --step=20 run
  ```
- **provider_uri** must point to `.../qlib_bin/` (not `.../cn/`)
- **Always use `csi500_dyn`** (dynamic constituents) instead of static `csi500` — static pool has severe survivorship bias (only ~329-411 stocks in historical periods vs expected 500)
- DDG-DA requires >=48GB RAM; not viable on 30GB machines

## Data

Binary data path: `/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin/`
- Calendar: 2010-01-04 ~ present (continuously updated)
- Stocks: ~5,187 (all market)
- Pools: `csi300`, `csi500` (static, avoid), `csi500_dyn` (recommended), `csi1000`
- Base features: open, high, low, close, volume, vwap
- Custom alpha (precomputed, not yet used in rolling experiments): alpha_adx_trend, alpha_boll_position, alpha_cci_extreme, alpha_macd_hist, alpha_rsi_divergence, alpha_winner_rate

## Architecture

### Qlib Source (`qlib/`)

Upstream Microsoft Qlib framework. Key modules:
- `qlib/data/` — data loading, expressions/operators (`ops.py`), Cython libs (`_libs/rolling.pyx`, `expanding.pyx`)
- `qlib/contrib/model/` — model implementations: `gbdt.py` (LightGBM), `double_ensemble.py` (DEnsembleModel), `xgboost.py`, `linear.py`, plus PyTorch models (LSTM, GRU, Transformer, HIST, etc.)
- `qlib/contrib/data/handler.py` — data handlers including `Alpha158` (158 built-in factors)
- `qlib/contrib/rolling/base.py` — `Rolling` base class for rolling retrain; `ddgda.py` for DDG-DA meta-learning
- `qlib/contrib/strategy/` — portfolio strategies including `TopkDropoutStrategy`
- `qlib/workflow/` — experiment workflow orchestration, record templates (`record_temp.py`)
- `qlib/backtest/` — backtesting engine
- `qlib/cli/run.py` — CLI entry point (`qrun` command)

### HATS Workflows (`hats_workflows/`)

Research and production overlay. Key files:

| File | Purpose |
|------|---------|
| `rolling_benchmark.py` | Rolling retrain entry point (wraps `qlib.contrib.rolling.base.Rolling`) |
| `run_workflow.py` | Static train/predict entry |
| `custom_handler.py` | `Alpha158PlusCustom` — extends Alpha158 with 6 custom factors (164 total) |
| `signal_duckdb_pipeline.py` | Signal ingestion, order generation, broker reconciliation via DuckDB |
| `topk_grid_search.py` | TopK parameter grid search |
| `ddgda_workflow.py` | DDG-DA meta-learning entry (needs >=48GB) |
| `EXPERIMENT_LOG.md` | Complete experiment log (all configs + results across phases) |
| `workflow_config_rolling_*_dyn.yaml` | Rolling configs with dynamic pool (recommended) |
| `configs/` | Phase 1/2 experiment configs |

### Config YAML Structure

Rolling configs (e.g., `workflow_config_rolling_double_ensemble_dyn.yaml`) follow this pattern:
- `qlib_init` — provider_uri + region
- `market` / `benchmark` — stock pool and benchmark index
- `data_handler_config` — time ranges, instruments
- `port_analysis_config` — TopkDropout strategy + backtest params (account, costs, thresholds)
- `task` — model class/kwargs, dataset (handler + segments), record templates

### Production Pipeline

Daily cron sequence (Asia/Shanghai):
1. 19:00-21:30: Data sync (DuckDB market/chip/factor data)
2. 22:00: Qlib binary data update
3. 22:30: Daily signal generation (DE + LGBM) → DuckDB `qlib_predictions` + `qlib_orders`
4. 23:00: Reconciliation vs broker executions
5. Monthly: Model retrain + deploy

Production scripts live in HATS project (`/home/tanlu/myworkspace/HATS/scripts/daily_signal_scheduler.py`).

## Current Best Model

| Parameter | Value |
|-----------|-------|
| Method | Rolling Retrain |
| Model | DoubleEnsemble (6 LightGBM sub-models, sample reweighting + feature selection) |
| Features | Alpha158 (158 factors) |
| Pool | CSI500 dynamic (`csi500_dyn`, benchmark SH000905) |
| Horizon | 5 (T+5 prediction) |
| Step | 20 (retrain every 20 trading days) |
| Train | 2015-01-01 ~ 2022-12-31 |
| Valid | 2023-01-01 ~ 2024-12-31 |
| Test | 2025-01-01 ~ 2026-01-30 |
| Backtest | TopkDropout (Top50, drop 5/day, 100M capital) |

Results: Rank IC 0.0469, ICIR 0.4907, annualized excess 12.2% (with costs), IR 1.48, max drawdown -9.4%.

## Key Findings

1. Static training is not viable (Rank IC < 0.03) — must use Rolling Retrain
2. h=5 (T+5 holding) is optimal balance of signal quality and returns
3. step=20 is optimal; more frequent retraining overfits
4. DoubleEnsemble is best overall; XGBoost has highest excess return (16.5%) but larger drawdown
5. Custom alpha factors not yet integrated into rolling experiments (handler ready)
