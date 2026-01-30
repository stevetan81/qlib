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
| `model_path` | 模型路径: models/current |
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
