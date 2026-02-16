# HATS Qlib 模型研究工作区

## 角色定义

资深量化模型研究员，具备优秀的编程能力。使用 Qlib workflow 进行研究。

## 研究目标

通过 Qlib 研究优化基于 A 股短线波段策略（持股 1-10 天）模型，获取最大化收益。

## 项目定位

本工作区专注于 Qlib 量化模型研究。HATS 项目已做架构分离：
- **数据采集** — HATS 项目独立处理
- **Qlib 量化分析** — 本工作区（`/home/tanlu/myworkspace/qlib/`）
- **LLM 分析** — HATS 项目独立处理

## 数据源

数据位于 `/home/tanlu/myworkspace/HATS/data/`，通过 Qlib 二进制格式桥接。

### 完整数据目录结构

```
/home/tanlu/myworkspace/HATS/data/
├── qlib_export/cn/
│   ├── qlib_bin/               # Qlib 二进制数据（模型训练用）
│   │   ├── calendars/day.txt   # 交易日历 2010-01-04 ~ 今天（持续更新）
│   │   ├── instruments/        # 股票池
│   │   │   ├── all.txt         # 全市场 5,187 只
│   │   │   ├── csi300.txt
│   │   │   ├── csi500.txt
│   │   │   └── csi1000.txt     # 999 只（静态列表）
│   │   └── features/           # 5,191 个股票目录，每个含 OHLCV + 自定义因子
│   └── csv_export/             # CSV 格式导出（含指数 SH000300/852/905）
├── cn/
│   ├── market/                 # 市场数据
│   ├── prediction/             # 预测结果
│   └── raw/                    # 原始数据
├── duckdb/                     # DuckDB 数据库（HATS 主数据源）
├── models/                     # 已有模型（cn_lgbm.pkl 等）
├── factor_analysis/            # 因子分析结果
├── universe/                   # 股票池定义
└── predictions/                # Qlib 预测输出目录
```

### Qlib 二进制数据

- **路径**: `/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin/`
- **日历范围**: 2010-01-04 ~ 2026-02-06（持续更新）
- **股票数量**: 5,187 只（全市场）
- **股票池**: CSI300 / CSI500 / CSI1000（999 只，静态列表）

### 可用特征

基础行情：
- open, high, low, close, volume, vwap

自定义 alpha 因子（预计算在 Qlib 二进制中）：
- alpha_adx_trend
- alpha_boll_position
- alpha_cci_extreme
- alpha_macd_hist
- alpha_rsi_divergence
- alpha_winner_rate

### 已有模型

`/home/tanlu/myworkspace/HATS/data/models/` 下有：
- cn_lgbm.pkl, hk_lgbm.pkl, us_lgbm.pkl, us_lightgbm.pkl

## 工作流 (`hats_workflows/`)

| 文件 | 用途 |
|------|------|
| `EXPERIMENT_LOG.md` | **完整实验记录（所有配置+结果）** |
| `rolling_benchmark.py` | Rolling 训练入口（Phase 2 主力） |
| `ddgda_workflow.py` | DDG-DA 入口（需 >=48GB 内存） |
| `workflow_config_rolling_lgbm.yaml` | Rolling LightGBM 配置 |
| `workflow_config_rolling_double_ensemble.yaml` | Rolling DoubleEnsemble 配置（最优） |
| `workflow_config_rolling_xgboost.yaml` | Rolling XGBoost 配置 |
| `workflow_config_rolling_linear.yaml` | Rolling Linear 配置 |
| `config_train.yaml` | 静态训练配置（CSI500） |
| `custom_handler.py` | Alpha158PlusCustom（164因子） |
| `run_workflow.py` | 静态训练入口脚本 |

### 当前最优模型配置

- **方法**: Rolling Retrain（滚动训练）
- **模型**: DoubleEnsemble（6个LightGBM子模型，样本重加权+特征选择）
- **特征**: Qlib Alpha158（内置 158 因子）
- **股票池**: CSI500（中证500, SH000905）
- **horizon**: 5（T+5 预测）
- **step**: 20（每 20 个交易日重新训练）
- **训练集**: 2015-01-01 ~ 2022-12-31
- **验证集**: 2023-01-01 ~ 2024-12-31
- **测试集**: 2025-01-01 ~ 2026-01-30
- **回测策略**: TopkDropout（Top50, 每日换 5 只, 1 亿本金）
- **运行**: `cd /tmp && python rolling_benchmark.py --conf_path=workflow_config_rolling_double_ensemble.yaml --horizon=5 --step=20 run`

### 当前最优结果

| 指标 | 值 |
|------|-----|
| Rank IC | 0.0469 |
| Rank ICIR | 0.4907 |
| 年化超额收益(含成本) | 12.2% |
| 信息比率 | 1.48 |
| 最大回撤 | -9.4% |

### 关键发现

1. 静态训练完全不可行（Rank IC < 0.03），必须使用 Rolling Retrain
2. h=5（T+5持仓）是信号质量与收益的最佳平衡
3. step=20 最优，更频繁重训反而过拟合
4. DoubleEnsemble 综合最优，XGBoost 超额收益最高（16.5%）
5. DDG-DA 需要 >=48GB 内存，30GB 机器不可行

## 注意事项

- 所有 Rolling 实验必须从 `/tmp` 运行（避免 qlib 源码导入冲突）
- provider_uri 必须指向 `.../qlib_bin/`（不是 `.../cn/`）
- 完整实验记录见 `hats_workflows/EXPERIMENT_LOG.md`
- CSI500 instruments 为静态列表（500 只），非动态成分股调整
- 自定义 alpha 因子尚未整合到 Rolling 实验（Alpha158PlusCustom handler 已就绪）
