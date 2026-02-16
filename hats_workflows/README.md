# HATS Qlib Workflows

A 股短线波段策略（持股 1-10 天）量化模型研究与生产工作流，基于 Qlib 框架。

## 当前最优配置

| 项目 | 值 |
|------|-----|
| 方法 | Rolling Retrain（滚动训练） |
| 模型 | DoubleEnsemble（6 个 LightGBM 子模型，样本重加权+特征选择） |
| 特征 | Qlib Alpha158（内置 158 因子） |
| 股票池 | CSI500 动态成分（`csi500_dyn`） |
| 预测周期 | T+5（5 个交易日） |
| 滚动步长 | 20 个交易日 |
| 回测策略 | TopkDropout（Top8, 每日换 1 只） |
| 基准指数 | SH000905（中证 500） |

### 关键指标（Rolling Retrain, 测试期 2025-01 ~ 2026-01）

| 指标 | 值 |
|------|-----|
| Rank IC | 0.0469 |
| Rank ICIR | 0.4907 |
| 年化超额收益（含成本） | 12.2% |
| 信息比率 | 1.48 |
| 最大回撤 | -9.4% |

## 目录结构

```
hats_workflows/
├── EXPERIMENT_LOG.md                              # 完整实验记录（Phase 0-11）
├── rolling_benchmark.py                           # Rolling Retrain 入口（主力）
├── run_workflow.py                                # 静态训练/预测入口
├── custom_handler.py                              # Alpha158PlusCustom handler（164 因子）
├── ddgda_workflow.py                              # DDG-DA 元学习入口（需 >=48GB）
├── signal_duckdb_pipeline.py                      # 信号落库 & 对账管道
├── auto_signal_scheduler.py                       # 自动化调度（本仓库副本）
├── topk_grid_search.py                            # TopK 参数网格搜索
│
├── config_train.yaml                              # 静态训练配置（CSI1000, LightGBM）
├── config_train_csi500_dyn.yaml                   # 静态训练配置（CSI500 动态）
├── config_predict.yaml                            # 全市场预测配置
├── benchmark_csi1000.yaml                         # CSI1000 基准配置
├── benchmark_signal_only.yaml                     # 信号评估配置
│
├── workflow_config_rolling_double_ensemble.yaml    # Rolling DE（静态池）
├── workflow_config_rolling_double_ensemble_dyn.yaml       # Rolling DE（动态池）★推荐
├── workflow_config_rolling_double_ensemble_dyn_deploy.yaml # Rolling DE 生产部署配置
├── workflow_config_rolling_de_164.yaml             # Rolling DE + 164 因子
├── workflow_config_rolling_de_164_dyn.yaml         # Rolling DE + 164 因子（动态池）
├── workflow_config_rolling_lgbm.yaml               # Rolling LightGBM
├── workflow_config_rolling_lgbm_dyn.yaml           # Rolling LightGBM（动态池）
├── workflow_config_rolling_xgboost.yaml            # Rolling XGBoost
├── workflow_config_rolling_xgboost_dyn.yaml        # Rolling XGBoost（动态池）
├── workflow_config_rolling_linear.yaml             # Rolling Linear
├── workflow_config_rolling_linear_dyn.yaml         # Rolling Linear（动态池）
│
├── configs/                                       # Phase 1 实验配置
│   ├── phase1_lgbm_label_t{1,3,5,10}[_dyn].yaml  # Label horizon 扫描
│   ├── phase1_lgbm_alpha158_plus.yaml             # Alpha158 + 自定义因子
│   ├── phase1_best_combined.yaml                  # 最优组合
│   └── phase2_rr_de_dyn_deploy_start_20251103.yaml # Phase 2 部署配置
│
└── models/                                        # 模型存储（gitignore）
    └── current -> *.pkl
```

## 数据源

```
/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin/
├── calendars/day.txt       # 交易日历（2010-01-04 ~ 持续更新）
├── instruments/
│   ├── all.txt             # 全市场 ~5,187 只
│   ├── csi300.txt          # 沪深 300
│   ├── csi500.txt          # 中证 500（静态，有幸存者偏差）
│   ├── csi500_dyn.txt      # 中证 500 动态成分 ★推荐
│   └── csi1000.txt         # 中证 1000
└── features/               # 5,191 个股票目录（OHLCV + 自定义 alpha）
```

可用特征：
- **基础行情**: open, high, low, close, volume, vwap
- **自定义 alpha**（预计算，尚未用于主实验）: alpha_adx_trend, alpha_boll_position, alpha_cci_extreme, alpha_macd_hist, alpha_rsi_divergence, alpha_winner_rate

## 使用方法

### Rolling Retrain（推荐）

所有 Rolling 实验**必须从 `/tmp` 运行**，避免 qlib 源码导入冲突。

```bash
# DoubleEnsemble Rolling（当前最优）
cd /tmp && python /home/tanlu/myworkspace/qlib/hats_workflows/rolling_benchmark.py \
  --conf_path=/home/tanlu/myworkspace/qlib/hats_workflows/workflow_config_rolling_double_ensemble_dyn.yaml \
  --horizon=5 --step=20 run

# LightGBM Rolling
cd /tmp && python /home/tanlu/myworkspace/qlib/hats_workflows/rolling_benchmark.py \
  --conf_path=/home/tanlu/myworkspace/qlib/hats_workflows/workflow_config_rolling_lgbm_dyn.yaml \
  --horizon=5 --step=20 run

# XGBoost Rolling
cd /tmp && python /home/tanlu/myworkspace/qlib/hats_workflows/rolling_benchmark.py \
  --conf_path=/home/tanlu/myworkspace/qlib/hats_workflows/workflow_config_rolling_xgboost_dyn.yaml \
  --horizon=5 --step=20 run
```

### 静态训练（仅用于快速验证）

```bash
# CSI500 动态池训练
python hats_workflows/run_workflow.py --mode train \
  --config hats_workflows/config_train_csi500_dyn.yaml

# 全市场预测
python hats_workflows/run_workflow.py --mode predict --date 2026-02-13
```

## 生产部署架构

```
┌──────────────────────────────────────────────────────────────────┐
│  Cron 定时任务（Asia/Shanghai 时区）                               │
├──────────────────────────────────────────────────────────────────┤
│  19:00  daily_sync.py           DuckDB 行情同步                   │
│  20:30  daily_sync.py           筹码绩效同步                       │
│  21:30  daily_sync.py           技术因子同步                       │
│  22:00  daily_qlib_update.py    Qlib 二进制数据更新                │
│  22:30  daily_signal_scheduler  run-daily   每日预测+落库(DE+LGBM)│
│  23:00  daily_signal_scheduler  run-reconcile 对账                │
│  每月首个周六 23:30  run-retrain-deploy  DE+LGBM 重训+部署         │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────┐
│  DuckDB（HATS/data/cn/raw/tushare.duckdb）          │
│  ├── qlib_predictions  每日预测分数（DE + LGBM）    │
│  ├── qlib_orders       BUY/SELL 信号（DE + LGBM）   │
│  ├── qlib_executions   券商成交回报                 │
│  └── qlib_reconcile    信号 vs 成交对账             │
└──────────────────────────────────────────────────┘
         │
         ▼
   HATS/models/qlib_deployed_current.pkl          (DE, 月度重训)
   HATS/models/qlib_deployed_lgbm_csi500_dyn.pkl  (LGBM, 月度重训)
```

### Cron 管理

```bash
# 安装/更新 cron
cd /home/tanlu/myworkspace/HATS
python scripts/daily_signal_scheduler.py install-cron \
  --cron-user tanlu --topk 8 --n-drop 1

# 查看 cron 配置
python scripts/daily_signal_scheduler.py print-cron

# 移除 cron
python scripts/daily_signal_scheduler.py remove-cron --cron-user tanlu
```

### 手动运行

```bash
cd /home/tanlu/myworkspace/HATS

# 手动跑某日预测
python scripts/daily_signal_scheduler.py run-daily --date 2026-02-13

# 手动对账
python scripts/daily_signal_scheduler.py run-reconcile --date 2026-02-13

# 手动重训+部署（DE + LGBM）
python scripts/daily_signal_scheduler.py run-retrain-deploy --train-runner hats \
  --extra-train-configs configs/qlib_train_lgbm_csi500_dyn.yaml
```

### 信号落库管道（底层工具）

```bash
# 预测结果落库
python hats_workflows/signal_duckdb_pipeline.py \
  --db-path /home/tanlu/myworkspace/HATS/data/cn/raw/tushare.duckdb \
  ingest-pred --pred-csv .../pred_20260213.csv \
  --model-name auto --topk 8 --n-drop 1

# 导入券商成交
python hats_workflows/signal_duckdb_pipeline.py \
  --db-path /home/tanlu/myworkspace/HATS/data/cn/raw/tushare.duckdb \
  import-exec --exec-csv .../executions_20260214.csv

# 对账
python hats_workflows/signal_duckdb_pipeline.py \
  --db-path /home/tanlu/myworkspace/HATS/data/cn/raw/tushare.duckdb \
  reconcile --trade-date 2026-02-14
```

## 关键发现

1. **静态训练完全不可行**（Rank IC < 0.03），必须使用 Rolling Retrain
2. **h=5（T+5 持仓）**是信号质量与收益的最佳平衡
3. **step=20 最优**，更频繁重训反而过拟合
4. **DoubleEnsemble 综合最优**，XGBoost 超额收益最高（16.5%）但回撤大
5. **DDG-DA 需要 >=48GB 内存**，30GB 机器不可行
6. **静态 `csi500` 有严重幸存者偏差**，历史区间成分数远少于 500，必须用 `csi500_dyn`
7. **自定义 alpha 因子**（alpha_adx_trend 等）尚未整合到 Rolling 实验，Alpha158PlusCustom handler 已就绪

## 依赖

- Python 3.10+
- Qlib（本仓库）
- LightGBM, XGBoost
- pandas, numpy, scipy
- DuckDB（生产落库）
