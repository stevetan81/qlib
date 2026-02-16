# HATS Qlib Workflows

HATS 量化模型训练和预测工作流，基于 Qlib 框架。

## 目录结构

```
hats_workflows/
├── config_train.yaml      # 训练配置 (CSI1000 + LightGBM)
├── config_predict.yaml    # 预测配置 (全市场)
├── run_workflow.py        # 工作流入口脚本
├── models/                # 模型存储目录
│   └── current -> lgbm_csi1000_YYYYMMDD.pkl  # 当前模型软链接
└── README.md
```

## 数据流

```
HATS DuckDB (raw data)
    ↓
scripts/extract_qlib_data.py (前复权 + normalize)
    ↓
Qlib binary format (~/.qlib/qlib_data 或 HATS/data/qlib_export/cn)
    ↓
run_workflow.py --mode train (CSI1000 训练)
    ↓
models/lgbm_csi1000_YYYYMMDD.pkl
    ↓
run_workflow.py --mode predict (全市场预测)
    ↓
HATS/data/predictions/pred_YYYYMMDD.csv
    ↓
HATS scripts/qlib_import_predictions.py (导入 DuckDB)
```

## 使用方法

### 训练模型

```bash
# 使用默认配置训练
python run_workflow.py --mode train

# 使用自定义配置
python run_workflow.py --mode train --config /path/to/config.yaml
```

训练完成后：
- 模型保存到 `models/lgbm_csi1000_YYYYMMDD.pkl`
- `models/current` 软链接指向最新模型
- 输出 Rank IC 指标

### 预测

```bash
# 预测今天
python run_workflow.py --mode predict

# 预测指定日期
python run_workflow.py --mode predict --date 2026-01-30
```

预测结果：
- 输出到 `HATS/data/predictions/pred_YYYYMMDD.csv`
- 包含 datetime, instrument, score, rank 列

## 配置说明

### config_train.yaml

| 参数 | 说明 |
|------|------|
| `market` | 训练范围: csi1000 |
| `segments.train` | 训练集: 2020-01-01 ~ 2024-12-31 |
| `segments.valid` | 验证集: 2025-01-01 ~ 2025-06-30 |
| `segments.test` | 测试集: 2025-07-01 ~ 当前 |
| `model_config` | LightGBM 超参数 (已优化) |

### config_predict.yaml

| 参数 | 说明 |
|------|------|
| `market` | 预测范围: all (全市场) |
| `model_path` | 模型路径: `HATS/models/qlib_deployed_current.pkl` |
| `output.path` | 输出目录: HATS/data/predictions |

## 与 HATS 集成

### 日常流程 (每日 16:00)

```bash
# 1. 同步数据到 DuckDB
python scripts/daily_sync.py

# 2. 导出 Qlib 格式
python scripts/extract_qlib_data.py

# 3. 运行预测
cd /home/tanlu/myworkspace/qlib
python hats_workflows/run_workflow.py --mode predict

# 4. 导入预测结果
cd /home/tanlu/myworkspace/HATS
python scripts/qlib_import_predictions.py
```

### DuckDB 信号落库与实盘对账

如果你希望把每日信号直接放进 DuckDB，并分析“预测/信号”和“实盘成交”差异，可使用：

```bash
# 1) 预测结果落库，并生成次日开盘 orders_YYYYMMDD.csv
python hats_workflows/signal_duckdb_pipeline.py \
  --db-path /home/tanlu/myworkspace/HATS/data/cn/raw/tushare.duckdb \
  ingest-pred \
  --pred-csv /home/tanlu/myworkspace/HATS/data/predictions/pred_20260210.csv \
  --model-name de_h5_s20_open_topk8 \
  --topk 8 \
  --n-drop 1
```

```bash
# 2) 回写券商成交数据（CSV）到 DuckDB
python hats_workflows/signal_duckdb_pipeline.py \
  --db-path /home/tanlu/myworkspace/HATS/data/cn/raw/tushare.duckdb \
  import-exec \
  --exec-csv /path/to/broker_executions_20260211.csv \
  --broker-name broker_a
```

```bash
# 3) 对账：输出“计划信号 vs 实际成交”差异明细
python hats_workflows/signal_duckdb_pipeline.py \
  --db-path /home/tanlu/myworkspace/HATS/data/cn/raw/tushare.duckdb \
  reconcile \
  --trade-date 2026-02-11 \
  --model-name de_h5_s20_open_topk8
```

默认会自动创建并维护以下表：

- `qlib_predictions`: 每日全量预测分数与排名
- `qlib_orders`: 由 TopK 选股变化生成的 BUY/SELL 信号
- `qlib_executions`: 券商回报成交记录
- `qlib_reconcile`: 当日信号与实盘成交差异结果

### 全自动定时运行（Cron）

如果希望完全自动化，建议使用 **HATS 侧入口** 安装定时任务：

```bash
# 安装/更新 cron（工作日 19:40 跑预测+落库，20:10 跑成交回写+对账）
cd /home/tanlu/myworkspace/HATS
python scripts/daily_signal_scheduler.py install-cron \
  --cron-user tanlu \
  --model-name auto \
  --topk 8 \
  --n-drop 1
```

```bash
# 查看将要写入的 cron 配置
cd /home/tanlu/myworkspace/HATS
python scripts/daily_signal_scheduler.py print-cron
```

```bash
# 移除自动任务
cd /home/tanlu/myworkspace/HATS
python scripts/daily_signal_scheduler.py remove-cron --cron-user tanlu
```

默认配置：

- 时区：`Asia/Shanghai`
- `model-name=auto`：自动读取当前模型文件名（例如 `lgbm_csi1000_20260130`）
- 每日任务：`40 19 * * 1-5`（预测 -> DuckDB -> `orders_YYYYMMDD.csv`）
- 对账任务：`10 20 * * 1-5`（读取 `HATS/data/executions/executions_YYYYMMDD.csv`，落库并对账）
- 日志：`HATS/logs/auto_signal_daily.log` 与 `HATS/logs/auto_signal_reconcile.log`

### 重训练流程 (双周六 08:00)

```bash
# 检查是否需要重训练 (Rank IC < 0.03 或 距上次 > 14 天)
python scripts/weekly_retrain.py
```

## 模型质量指标

- **Rank IC**: 预测排名与实际收益排名的 Spearman 相关系数
- **Rank IC IR**: Rank IC 均值 / Rank IC 标准差
- **目标**: Rank IC > 0.03, IC IR > 0.3

## 依赖

- Python 3.10+
- Qlib (本仓库)
- LightGBM
- pandas, numpy, scipy
