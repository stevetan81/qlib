# HATS Qlib 实验记录（A股短线波段策略）

> 本文件记录所有量化模型实验的设计、配置和结果。
> 跨 session 和 AI Agent 共享参考。
> 最后更新: 2026-02-10

---

## 1. 研究概述

- **目标**: 基于 Qlib 框架优化 A 股短线波段策略（持股 1-10 天），最大化收益
- **股票池**: CSI500（中证 500，SH000905）
- **特征**: Qlib Alpha158（内置 158 因子）
- **框架**: 静态训练 → 滚动训练（Rolling Retrain）→ DDG-DA 元学习

---

## 2. 数据配置

| 项目 | 值 |
|------|-----|
| 数据源 | `/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin` |
| 日历范围 | 2010-01-04 ~ 2026-02-06 |
| 全市场股票数 | 5,187 |
| CSI500 成分股 | `csi500`（静态列表，⚠️幸存者偏差风险） / `csi500_dyn`（动态成分，推荐用于 benchmark/rolling） |
| 特征 | Alpha158（158 因子） |
| 基准指数 | SH000905（中证 500） |

### 2.1 重要更新：CSI500 股票池口径（静态 vs 动态）

近期我们做了一次“对齐 `examples/benchmarks_dynamic/` RR baseline”的验证，发现你自建数据里的 `csi500` instruments 属于**静态口径**（更接近“当前成分 + 上市日起算”），在历史区间会导致成分数显著少于 500，从而引入幸存者偏差并把 Topk 策略回测收益抬高到不可比的水平。

为解决该问题，已在自建数据目录新增动态 CSI500 成分文件（落盘，可长期复用）：
- `csi500_dyn`：`/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin/instruments/csi500_dyn.txt`
  - 2026-02-08：将末端区间的 `end_date` 从 2026-01-29 延伸到 2026-02-06（匹配当前日历范围；避免 2026-01-30 之后成分为空）

建议：
- 所有需要与微软 baseline 或 crowd 数据可比的实验（尤其 Rolling Retrain / benchmarks_dynamic）优先使用 `market: csi500_dyn`。
- 对历史区间回测（例如 2017–2020）若继续用静态 `csi500`，结果大概率偏乐观。

### 可用自定义因子（已预计算但未使用于主实验）
- alpha_adx_trend, alpha_boll_position, alpha_cci_extreme
- alpha_macd_hist, alpha_rsi_divergence, alpha_winner_rate

---

## 3. Phase 0 — Benchmarks_dynamic RR 基线对齐（CSI500，2017-01 ~ 2020-08）

### 3.1 实验目标

按 `examples/benchmarks_dynamic/` 的 Rolling Retrain（RR）思路，使用 **相同 RR 配置** 在两份数据上对比：
- 自建 Qlib 数据（你的导出数据）
- crowd-sourced 标准数据（`investment_data` release 的 `qlib_bin.tar.gz`）

目的是回答：为什么你自建数据离 baseline 很远？差异来自模型还是来自“市场/股票池定义”？

> 详细实验记录（含复现步骤、配置、问题清单、归档 JSON）：  
> `examples/benchmarks_dynamic/csi500_rr_compare/RR_BENCHMARK_COMPARISON.md`

### 3.2 实验设计（对齐 RR baseline）

- 数据集/特征：Alpha158
- Rolling：`qlib.contrib.rolling.base.Rolling`
- horizon=20，step=20（baseline 设定）
- 组合：TopkDropout(topk=50, n_drop=5)
- 成交价：deal_price=close
- 成本：open_cost=0.0005, close_cost=0.0015, min_cost=5
- 初始资金：account=100,000,000（与 baseline 一致）
- benchmark：SH000905
- 市场（关键变量）：`csi500` vs `csi500_dyn`

配置文件（已加入仓库，便于复现）：
- `examples/benchmarks_dynamic/csi500_rr_compare/workflow_config_linear_Alpha158_csi500.yaml`
- `examples/benchmarks_dynamic/csi500_rr_compare/workflow_config_lightgbm_Alpha158_csi500.yaml`
- `examples/benchmarks_dynamic/csi500_rr_compare/workflow_config_doubleensemble_Alpha158_csi500.yaml`
- 以及对应的 `*_csi500_dyn.yaml`（market=动态池）

### 3.3 关键现象：静态 `csi500` 会导致成分数 < 500（幸存者偏差）

对比测试期（2017-01 ~ 2020-08）不同日期“当日可用成分数”（按交易日过滤）：
- crowd 数据：始终 500（符合 CSI500）
- 自建数据（静态 `csi500`）：明显少于 500  
  - 2017-01-03：329
  - 2018-01-02：364
  - 2019-01-02：381
  - 2020-07-31：411

这会直接导致 RR 回测显著偏乐观，无法与 baseline 可比。

### 3.4 RR 对比结果（horizon=20, step=20）

| Model | Dataset | IC | ICIR | Rank IC | Rank ICIR | Ann. Ret (excess, with cost) | IR | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| RR[Linear] | crowd | 0.0742 | 0.6764 | 0.0963 | 0.8707 | 7.00% | 0.9697 | -17.57% |
| RR[Linear] | 自建（静态 csi500） | 0.0894 | 0.7028 | 0.1086 | 0.8153 | 24.81% | 3.1520 | -13.53% |
| RR[Linear] | 自建（动态 csi500_dyn） | 0.0728 | 0.6081 | 0.0980 | 0.8097 | 8.49% | 1.1644 | -16.70% |
| RR[LightGBM] | crowd | 0.0806 | 0.7545 | 0.0989 | 0.9162 | 9.18% | 1.2955 | -15.50% |
| RR[LightGBM] | 自建（静态 csi500） | 0.0840 | 0.6723 | 0.0979 | 0.7590 | 24.18% | 3.1271 | -10.54% |
| RR[LightGBM] | 自建（动态 csi500_dyn） | 0.0752 | 0.6558 | 0.0970 | 0.8477 | 13.32% | 1.9646 | -15.57% |

结论：
- 使用动态成分后，RR[Linear] 已基本与 crowd 对齐；RR[LightGBM] 仍略偏强，但已从“不可比的虚高”收敛到可讨论的差异。
- 后续若要对齐 DoubleEnsemble baseline，必须先保证 `market` 口径一致（先 1 后 2）。

### 3.5 RR + DoubleEnsemble 快速验证（step=120）

由于 DoubleEnsemble 单次训练耗时较长，`step=20` 全量 rolling 属于小时级。为先验证方向，我用 `step=120` 做了 RR 对比（仍在“自建数据 + 动态成分”口径下）：

| Model | step | IC | ICIR | Rank IC | Rank ICIR | Ann. Ret (excess, with cost) | IR | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| RR[LightGBM] | 120 | 0.0736 | 0.6407 | 0.0954 | 0.8316 | 12.11% | 1.7686 | -16.26% |
| RR[DoubleEnsemble] | 120 | 0.0810 | 0.6935 | 0.1024 | 0.8677 | 13.54% | 1.9988 | -12.09% |

结论：
- 在动态成分口径下，DoubleEnsemble 相比 LGBM 在收益/IR 与回撤上均有改善趋势。
- 下一步如果要对齐微软 baseline 的 `step=20`，需要先确认计算资源/耗时预算。

### 3.6 产物归档（便于复查/复现）

指标 JSON 已归档到：
- `examples/benchmarks_dynamic/csi500_rr_compare/run_outputs/rr_compare_csi500_20260207_212929/`（自建静态 vs crowd；Linear/LGBM）
- `examples/benchmarks_dynamic/csi500_rr_compare/run_outputs/rr_compare_csi500_own_dynpool_20260207_222822/`（自建动态；step=20；Linear/LGBM）
- `examples/benchmarks_dynamic/csi500_rr_compare/run_outputs/rr_compare_csi500_own_dynpool_rr_step120_20260207_230805/`（自建动态；step=120；LGBM/DoubleEnsemble）

### 3.7 本次对齐实验暴露的工程坑（需长期记录）

1) Rolling 不读取 YAML 的 `qlib_init`：需要外部 `auto_init/qlib.init` 指定 `provider_uri`  
2) handler cache 可能跨数据源复用：`Alpha158.<hash>.pkl` hash 不包含 provider_uri，需隔离 conf 目录或显式指定 cache 路径  
3) instruments 代码大小写不一致：crowd=SH/SZ，你的数据目录=sh/sz（需要适配）  
4) 仓库源码版 Qlib 未编译扩展：在仓库目录内导入会 `ModuleNotFoundError: qlib.data._libs.rolling`，建议从 `/tmp` 运行并导入已安装版 Qlib  
5) 自建数据缺少 `day_future.txt` 会出现 warning（对历史回测通常不致命，但需注意未来日历依赖）

---

## 4. Phase 1 — 静态训练基线

> ⚠️重要提示：本 Phase 1 的实验使用 `market: csi500`（静态口径）。该口径在历史区间会导致可用成分数显著 <500，并存在幸存者偏差风险。  
> 若要与 `benchmarks_dynamic` 或严谨 walk-forward 结果可比，建议后续补跑一套 `market: csi500_dyn` 的对照实验（见 Phase 0 对齐结论）。

### 4.1 实验设计

对比不同标签周期（T+1/T+3/T+5/T+10）对静态训练的影响。

**公共配置**:
```yaml
model: LGBModel (LightGBM)
handler: Alpha158 (158 factors)
market: csi500
benchmark: SH000905
train: 2020-01-01 ~ 2024-12-31
valid: 2025-01-01 ~ 2025-06-30
test: 2025-07-01 ~ 2026-01-30
backtest: TopkDropout(topk=50, n_drop=5), account=100M
```

**LightGBM 超参数**:
```yaml
loss: mse
colsample_bytree: 0.8879
learning_rate: 0.0421
subsample: 0.8789
lambda_l1: 205.6999
lambda_l2: 580.9768
max_depth: 8
num_leaves: 210
num_threads: 20
```

### 4.2 标签实验结果（Phase 1.2）

| 实验 | 标签公式 | IC | ICIR | Rank IC | Rank ICIR |
|------|----------|-----|------|---------|-----------|
| T+1 | `Ref($close,-2)/Ref($close,-1)-1` | -0.0081 | -0.0458 | 0.0244 | 0.1205 |
| **T+3** | `Ref($close,-4)/Ref($close,-1)-1` | **-0.0023** | **-0.0130** | **0.0261** | **0.1320** |
| T+5 | `Ref($close,-6)/Ref($close,-1)-1` | -0.0044 | -0.0253 | 0.0216 | 0.1094 |
| T+10 | `Ref($close,-11)/Ref($close,-1)-1` | -0.0194 | -0.1095 | 0.0118 | 0.0620 |

**结论**:
- 所有静态训练 IC 均为负值，Rank IC < 0.03 — 远低于目标（0.045）
- T+3 略优于其他，但整体静态训练**不足以产生可靠信号**
- 必须转向 Rolling Retrain 框架

### 4.3 配置文件

| 实验 | 配置文件 |
|------|---------|
| T+1 | `hats_workflows/configs/phase1_lgbm_label_t1.yaml` |
| T+1 (dyn) | `hats_workflows/configs/phase1_lgbm_label_t1_dyn.yaml` |
| T+3 | `hats_workflows/configs/phase1_lgbm_label_t3.yaml` |
| T+3 (dyn) | `hats_workflows/configs/phase1_lgbm_label_t3_dyn.yaml` |
| T+5 | `hats_workflows/configs/phase1_lgbm_label_t5.yaml` |
| T+5 (dyn) | `hats_workflows/configs/phase1_lgbm_label_t5_dyn.yaml` |
| T+10 | `hats_workflows/configs/phase1_lgbm_label_t10.yaml` |
| T+10 (dyn) | `hats_workflows/configs/phase1_lgbm_label_t10_dyn.yaml` |

### 4.4 Phase 1 重跑（动态池 csi500_dyn，2026-02-08）

背景：Phase 1 原始结果使用静态 `csi500`（存在幸存者偏差风险）。为与后续 rolling/benchmark 口径一致，这里用 **`market: csi500_dyn`** 复跑同一组标签实验（时间切分不变）。

配置文件（新增）：
- `hats_workflows/configs/phase1_lgbm_label_t1_dyn.yaml`
- `hats_workflows/configs/phase1_lgbm_label_t3_dyn.yaml`
- `hats_workflows/configs/phase1_lgbm_label_t5_dyn.yaml`
- `hats_workflows/configs/phase1_lgbm_label_t10_dyn.yaml`

运行输出（mlruns）：
- `/tmp/hats_phase1_dyn_20260208_092005/mlruns`

结果（动态池）：

| 实验 | market | IC | ICIR | Rank IC | Rank ICIR | 年化超额(含成本) | 信息比率 | 最大回撤 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| T+1 | csi500_dyn | -0.0176 | -0.0867 | 0.0320 | 0.1476 | -32.30% | -2.0045 | -24.79% |
| T+3 | csi500_dyn | -0.0259 | -0.1325 | 0.0285 | 0.1379 | -33.44% | -2.1659 | -23.83% |
| T+5 | csi500_dyn | -0.0294 | -0.1508 | 0.0213 | 0.1023 | -32.18% | -2.0659 | -23.14% |
| T+10 | csi500_dyn | -0.0471 | -0.2524 | -0.0029 | -0.0141 | -33.16% | -2.2414 | -24.37% |

结论（动态池）：
- 静态训练在动态池口径下仍然不可用：Rank IC 最高仅 0.032（远低于 0.045），且成本后超额收益为负。
- Phase 1 的“静态训练不行 → 必须 rolling”的结论 **在动态池口径下仍成立**。

---

## 5. Phase 2 — Rolling Retrain（滚动训练）

> ⚠️重要提示：本 Phase 2 的 rolling 实验历史上使用 `market: csi500`（静态口径）。例如在自建数据中：  
> - 2015-01-05：`csi500` 仅 298 只，而 `csi500_dyn` 为 500 只  
> - 2023-01-03：`csi500` 仅 476 只，而 `csi500_dyn` 为 500 只  
> 建议：后续把 Phase 2/2+ 的关键实验（至少最优的 h=5,s=20 的 LGBM/DE）用 `csi500_dyn` 复跑一遍，再据此决定是否继续投入算力做更细 rolling step（“先 1 后 2”）。

### 5.1 Rolling 框架说明

基于 `qlib.contrib.rolling.base.Rolling` 基类：
- **expanding window**: 训练窗口从固定起点扩展到当前时刻
- **sliding test window**: 每 `step` 个交易日滑动一次测试窗口
- **horizon**: 预测天数，标签自动调整为 `Ref($close, -(horizon+1)) / Ref($close, -1) - 1`
- **trunc_days**: 截断 `horizon+1` 天防止信息泄露

### 5.2 公共 Rolling 配置

```yaml
model: LGBModel (LightGBM)
handler: Alpha158 (158 factors)
market: csi500   # ⚠️注意：历史滚动实验若需可比性，建议切换到 csi500_dyn（见 Phase 0）
benchmark: SH000905
data_start: 2015-01-01
data_end: 2026-01-30
fit_start: 2015-01-01
fit_end: 2022-12-31
train: 2015-01-01 ~ 2022-12-31
valid: 2023-01-01 ~ 2024-12-31
test: 2025-01-01 ~ 2026-01-30
backtest: TopkDropout(topk=50, n_drop=5), account=100M
```

**LightGBM Rolling 超参数**（对齐官方 dynamic benchmark）:
```yaml
loss: mse
colsample_bytree: 0.8879
learning_rate: 0.2        # 注意: 比静态训练高（0.2 vs 0.0421）
subsample: 0.8789
lambda_l1: 205.6999
lambda_l2: 580.9768
max_depth: 8
num_leaves: 210
num_threads: 20
```

### 5.3 Horizon 实验结果

| 实验 | horizon | step | tasks | IC | ICIR | Rank IC | Rank ICIR | 年化超额(含成本) | 信息比率 | 最大回撤 |
|------|---------|------|-------|-----|------|---------|-----------|-----------------|---------|---------|
| RR-h1-s20 | 1 | 20 | 14 | 0.0098 | 0.0792 | 0.0180 | 0.1730 | 16.1% | 1.23 | -14.7% |
| RR-h3-s20 | 3 | 20 | 14 | 0.0283 | 0.2488 | 0.0341 | 0.3439 | 8.0% | 0.82 | -13.2% |
| **RR-h5-s20** | **5** | **20** | **14** | **0.0401** | **0.3908** | **0.0463** | **0.5106** | **7.1%** | **0.83** | **-12.5%** |
| RR-h10-s20 | 10 | 20 | 14 | 0.0422 | 0.3802 | 0.0470 | 0.5018 | 1.0% | 0.11 | -14.2% |

**结论**:
- **h=5 是最优 horizon**：Rank IC=0.0463（超过 Phase 1 目标 0.045），Rank ICIR=0.5106（超过 Phase 2 目标 0.55 接近）
- h=1 超额收益最高（16.1%），但信号质量差（Rank IC=0.018）— 高换手率贡献收益
- h=10 信号质量高但超额收益极低（1.0%）— 持仓太长摩擦损耗大
- h=5 在**信号质量和收益之间最佳平衡**

### 5.4 Step 优化实验（固定 h=5）

| 实验 | step | tasks | Rank IC | Rank ICIR | 年化超额(含成本) | 信息比率 | 最大回撤 |
|------|------|-------|---------|-----------|-----------------|---------|---------|
| **RR-h5-s20** | **20** | **14** | **0.0463** | **0.5106** | **7.1%** | **0.83** | **-12.5%** |
| RR-h5-s10 | 10 | 27 | 0.0445 | 0.4794 | 7.3% | 0.88 | -11.6% |
| RR-h5-s5 | 5 | 53 | 0.0404 | 0.4308 | 3.2% | 0.37 | -15.1% |

**结论**:
- **step=20 最优**：Rank IC 和 Rank ICIR 都最高
- 更频繁的重训（step=10/5）并不能提升性能，反而因过拟合降低了信号质量
- step=5 过度拟合导致超额收益下降到 3.2%

### 5.5 多模型 Rolling 对比（固定 h=5, s=20）

| 模型 | IC | ICIR | Rank IC | Rank ICIR | 年化超额(含成本) | 信息比率 | 最大回撤 |
|------|-----|------|---------|-----------|-----------------|---------|---------|
| LightGBM | 0.0401 | 0.3908 | 0.0463 | 0.5106 | 7.1% | 0.83 | -12.5% |
| XGBoost | 0.0349 | 0.3671 | 0.0399 | 0.4822 | 16.5% | 1.97 | -10.7% |
| Linear (Ridge α=0.05) | 0.0225 | 0.2262 | 0.0424 | 0.4513 | 2.4% | 0.25 | -14.2% |
| **DoubleEnsemble** | **0.0426** | **0.4233** | **0.0469** | **0.4907** | **12.2%** | **1.48** | **-9.4%** |

**模型配置差异**:

**XGBoost**:
```yaml
class: XGBModel
module_path: qlib.contrib.model.xgboost
kwargs:
    colsample_bytree: 0.8879
    eta: 0.2
    max_depth: 8
    subsample: 0.8789
    nthread: 20
```

**Linear (Ridge)**:
```yaml
class: LinearModel
module_path: qlib.contrib.model.linear
kwargs:
    estimator: ridge
    alpha: 0.05
```

**DoubleEnsemble**:
```yaml
class: DEnsembleModel
module_path: qlib.contrib.model.double_ensemble
kwargs:
    base_model: gbm
    loss: mse
    num_models: 6
    enable_sr: true     # sample reweighting
    enable_fs: true     # feature selection
    alpha1: 1
    alpha2: 1
    bins_sr: 10
    bins_fs: 5
    decay: 0.5
    epochs: 28
    # LightGBM params same as base
```

**结论**:
- **DoubleEnsemble 综合最优**：Rank IC=0.0469（最高），超额收益 12.2%，最大回撤仅 -9.4%（最小），信息比率 1.48
- **XGBoost 超额收益最高**（16.5%，信息比率 1.97），但 Rank IC 略低（0.0399）
- **LightGBM Rank ICIR 最高**（0.5106），信号最稳定
- **Linear 表现一般**，超额收益仅 2.4%
- **综合排名**: DoubleEnsemble > XGBoost > LightGBM > Linear

### 5.6 配置文件

| 实验 | 入口脚本 | 配置文件 |
|------|---------|---------|
| LightGBM Rolling | `rolling_benchmark.py` | `workflow_config_rolling_lgbm.yaml` |
| LightGBM Rolling (dyn) | `rolling_benchmark.py --conf_path=workflow_config_rolling_lgbm_dyn.yaml` | `workflow_config_rolling_lgbm_dyn.yaml` |
| XGBoost Rolling | `rolling_benchmark.py --conf_path=workflow_config_rolling_xgboost.yaml` | `workflow_config_rolling_xgboost.yaml` |
| XGBoost Rolling (dyn) | `rolling_benchmark.py --conf_path=workflow_config_rolling_xgboost_dyn.yaml` | `workflow_config_rolling_xgboost_dyn.yaml` |
| Linear Rolling | `rolling_benchmark.py --conf_path=workflow_config_rolling_linear.yaml` | `workflow_config_rolling_linear.yaml` |
| Linear Rolling (dyn) | `rolling_benchmark.py --conf_path=workflow_config_rolling_linear_dyn.yaml` | `workflow_config_rolling_linear_dyn.yaml` |
| DoubleEnsemble Rolling | `rolling_benchmark.py --conf_path=workflow_config_rolling_double_ensemble.yaml` | `workflow_config_rolling_double_ensemble.yaml` |
| DoubleEnsemble Rolling (dyn) | `rolling_benchmark.py --conf_path=workflow_config_rolling_double_ensemble_dyn.yaml` | `workflow_config_rolling_double_ensemble_dyn.yaml` |

### 5.7 运行命令

```bash
# 所有 Rolling 实验从 /tmp 运行（避免 qlib 源码导入冲突）
cd /tmp

# LightGBM Rolling (各 horizon)
python /path/to/rolling_benchmark.py --horizon=1 --step=20 run
python /path/to/rolling_benchmark.py --horizon=3 --step=20 run
python /path/to/rolling_benchmark.py --horizon=5 --step=20 run
python /path/to/rolling_benchmark.py --horizon=10 --step=20 run

# Step 优化
python /path/to/rolling_benchmark.py --horizon=5 --step=10 run
python /path/to/rolling_benchmark.py --horizon=5 --step=5 run

# 多模型对比
python /path/to/rolling_benchmark.py --conf_path=/path/to/workflow_config_rolling_xgboost.yaml --horizon=5 --step=20 run
python /path/to/rolling_benchmark.py --conf_path=/path/to/workflow_config_rolling_linear.yaml --horizon=5 --step=20 run
python /path/to/rolling_benchmark.py --conf_path=/path/to/workflow_config_rolling_double_ensemble.yaml --horizon=5 --step=20 run

# (Restart) 动态池版本（market=csi500_dyn）
python /path/to/rolling_benchmark.py --conf_path=/path/to/workflow_config_rolling_lgbm_dyn.yaml --horizon=5 --step=20 run
python /path/to/rolling_benchmark.py --conf_path=/path/to/workflow_config_rolling_xgboost_dyn.yaml --horizon=5 --step=20 run
python /path/to/rolling_benchmark.py --conf_path=/path/to/workflow_config_rolling_linear_dyn.yaml --horizon=5 --step=20 run
python /path/to/rolling_benchmark.py --conf_path=/path/to/workflow_config_rolling_double_ensemble_dyn.yaml --horizon=5 --step=20 run
```

### 5.8 Phase 2 重跑（动态池 csi500_dyn，2026-02-08）

目标：把 Phase 2 的关键结论（horizon/step/模型选择）在 **动态成分池** 口径下重新验证，避免静态池造成的幸存者偏差影响决策。

运行输出（mlruns）：
- `/tmp/hats_phase2_rolling_dyn_20260208_092935/mlruns`

#### 5.8.1 Horizon 扫描（LGBM, step=20, market=csi500_dyn）

| 实验 | horizon | step | tasks | IC | ICIR | Rank IC | Rank ICIR | 年化超额(含成本) | 信息比率 | 最大回撤 |
|------|---------|------|-------|---:|---:|---:|---:|---:|---:|---:|
| RR-dyn-h1-s20 | 1 | 20 | 14 | 0.0207 | 0.2087 | 0.0175 | 0.1871 | 6.83% | 0.85 | -12.10% |
| RR-dyn-h3-s20 | 3 | 20 | 14 | 0.0200 | 0.1778 | 0.0321 | 0.3441 | -0.73% | -0.08 | -15.08% |
| **RR-dyn-h5-s20** | **5** | **20** | **14** | **0.0278** | **0.2582** | **0.0430** | **0.4768** | **1.99%** | **0.19** | **-12.86%** |
| RR-dyn-h10-s20 | 10 | 20 | 14 | 0.0282 | 0.2744 | 0.0475 | 0.5252 | 0.44% | 0.04 | -15.85% |

观察：
- Rank IC/Rank ICIR 随 horizon 增大而提升，但组合收益（含成本）并不同步提升。
- horizon=1 仍然呈现“收益更高但信号质量低”的特征（高换手贡献更大）。

#### 5.8.2 Step 扫描（LGBM, horizon=5, market=csi500_dyn）

| 实验 | horizon | step | tasks | Rank IC | Rank ICIR | 年化超额(含成本) | 信息比率 | 最大回撤 |
|------|---------|------|-------|---:|---:|---:|---:|---:|
| RR-dyn-h5-s20 | 5 | 20 | 14 | 0.0430 | 0.4768 | 1.99% | 0.19 | -12.86% |
| RR-dyn-h5-s10 | 5 | 10 | 27 | 0.0418 | 0.4628 | -0.35% | -0.04 | -13.26% |
| **RR-dyn-h5-s5** | **5** | **5** | **53** | **0.0432** | **0.4819** | **4.63%** | **0.44** | **-10.71%** |

观察：
- 与静态池阶段的结论不同：在动态池口径下，step=5 在本测试期内显著提升了组合收益与回撤表现，但训练成本也更高（53 tasks）。
- 目前仅在 2025-01~2026-01 测试期验证过一次，是否稳定仍需进一步 walk-forward/多窗口验证。

#### 5.8.3 多模型对比（horizon=5, step=20, market=csi500_dyn）

> 说明：本小节包含 Linear/XGBoost 仅用于对照与 sanity check；按当前研究决策，后续主线只保留 **LightGBM + DoubleEnsemble**（不再投入算力在 Linear/XGBoost 上）。

| 模型 | IC | ICIR | Rank IC | Rank ICIR | 年化超额(含成本) | 信息比率 | 最大回撤 |
|------|---:|---:|---:|---:|---:|---:|---:|
| LightGBM | 0.0278 | 0.2582 | 0.0430 | 0.4768 | 1.99% | 0.19 | -12.86% |
| Linear (Ridge) | 0.0160 | 0.1319 | 0.0420 | 0.4035 | -5.71% | -0.49 | -16.98% |
| **XGBoost** | **0.0371** | **0.4045** | **0.0438** | **0.5591** | **9.78%** | **1.41** | **-5.54%** |
| DoubleEnsemble | 0.0360 | 0.3349 | 0.0482 | 0.5052 | 4.56% | 0.48 | -12.93% |

观察：
- **DoubleEnsemble** 仍然在 Rank IC 上最强（0.0482）。后续我们以 DoubleEnsemble 为主线，重点优化：股票池口径、step、以及 TopkDropout 参数。

#### 5.8.4 DoubleEnsemble 的 step=10 评估（部署口径，截取后段窗口，2026-02-09）

背景：你希望“尽量贴近实战”，因此我们最终关注的是部署口径（`deal_price=open`, `account=200000`, `topk=8,n_drop=1`）。  
但 DoubleEnsemble 的 rolling `step=10` 若在完整测试窗（2025-01~2026-01）跑完，预期耗时约 **6–7 小时**（约 27 tasks），不适合每次迭代都全量重跑。

因此本次采用“**从 step=10 的后段 rolling task 起点开始跑**”的方式做快速评估：
- 选择起点 `2025-11-03`（从 `2025-01-02` 起按 10 个交易日步进，平移 200 个交易日后对齐到该日期）
- 对应的分段整体平移为：
  - train: 2015-01-01 ~ 2023-11-01
  - valid: 2023-11-02 ~ 2025-10-31
  - test: 2025-11-03 ~ 2026-01-30
- 该设置等价于“完整 step=10 rolling 中，从第 21 个 rolling task 开始跑”（task 间相互独立，因此可跳过前段而不影响后段任务口径）

配置文件（已入仓，便于复现）：`hats_workflows/configs/phase2_rr_de_dyn_deploy_start_20251103.yaml`

运行输出：
- step=10 rolling 输出目录：`/tmp/hats_phase2_rr_de_dyn_deploy_start20251103_step10_20260209_061251/`
- pred.pkl：`/tmp/hats_phase2_rr_de_dyn_deploy_start20251103_step10_20260209_061251/mlruns/610401745595721579/6c5617043ff04dd69baec1bb53fa143d/artifacts/pred.pkl`

评估方式：
- 使用 `topk_grid_search.py` 固定 `topk=8,n_drop=1`，在 `2025-11-03 ~ 2026-01-30` 上计算超额（含成本）/IR/MaxDD

对比结果（同一评估窗、同一策略参数、同一成本假设）：
| step | 年化收益(含成本) | 基准收益 | 超额(含成本) | 超额(无成本) | IR | MaxDD |
|---:|---:|---:|---:|---:|---:|---:|
| **20**（来自完整 rolling 的 pred.pkl） | 72.6% | 51.7% | **20.9%** | 27.1% | 1.17 | -5.4% |
| **10**（本次后段窗口 rolling） | 51.8% | 51.7% | **0.1%** | 6.2% | 0.01 | -6.3% |

补充诊断（同窗）：
- RankIC：step=20 为 0.0560；step=10 为 0.0535（两者都不差）
- pred 日度排序相关（Spearman）：step=10 vs step=20 平均约 0.95，但 top8 选股集合日均重合仅约 4.9/8（集中组合对“排名微差”非常敏感）

结论（当前窗口）：
- 在该实战口径下，**step=10 并未带来收益提升，反而显著降低超额收益**；且训练成本约为 step=20 的 ~2×。
- 因此暂不推荐把 DoubleEnsemble 的重训频率从 `step=20` 提升到 `step=10`；维持 **每 20 个交易日重训一次**更稳健。

---

## 6. Phase 3 — DDG-DA 元学习

### 6.1 DDG-DA 说明

基于 `qlib.contrib.rolling.ddgda.DDGDA`，在 Rolling Retrain 基础上加入数据分布漂移自适应元学习。

**4 阶段流程**:
1. 训练代理模型 → 提取 Top N 重要特征
2. 构建 IC 矩阵（各数据段 × 时间点）
3. 训练 PredNet 元模型（学习 IC 时间演变模式）
4. 推理得到 TimeReweighter → 注入训练权重

### 6.2 DDG-DA 内存问题（致命）

| 尝试 | 参数 | RSS | 状态 | 原因 |
|------|------|-----|------|------|
| #1 (与3个Rolling并行) | 默认 (s=20, h30, f30) | 10.5GB | OOM Killed | 4进程总内存超30GB |
| #2 (与DoubleEnsemble并行) | 默认 | 16.0GB | OOM Killed | stage 3 + DE 4.4GB = 超限 |
| #3 (单独, 减少参数) | s=20, h15, f15 | 19.6GB | OOM Killed | 即使减参仍然 19.6GB |
| #4 (step=40) | **s=40, h10, f10, meta_end=2017** | ~8GB | **成功** | 结果不佳 |
| #5 (step=20, 最激进缩减) | **s=20, h10, f10, meta_end=2018** | 19.8GB | OOM Killed | MetaDatasetDS 内存无法控制 |

**结论**:
- DDG-DA + CSI500 + step=20 在 30GB 机器上 **不可行**
- MetaDatasetDS 在 stage 3 创建 meta tasks 时内存线性增长，无法通过减少参数控制
- 唯一成功的 step=40 版本性能劣于 plain Rolling step=20

### 6.3 DDG-DA step=40 结果（唯一成功运行）

```yaml
# 成功运行的参数
horizon: 5
step: 40
sim_task_model: gbdt
hist_step_n: 10
fea_imp_n: 10
meta_1st_train_end: "2017-12-31"
```

| 指标 | DDG-DA (step=40) | Plain Rolling LightGBM (step=20) |
|------|-------------------|----------------------------------|
| Rank IC | 0.0421 | **0.0463** |
| Rank ICIR | 0.4178 | **0.5106** |
| 年化超额(含成本) | 0.2% | **7.1%** |
| 信息比率 | 0.02 | **0.83** |
| 最大回撤 | -16.9% | **-12.5%** |

DDG-DA step=40 全面劣于 Rolling LightGBM step=20，因为：
1. step=40 重训频率不足，模型过时
2. hist_step_n=10 和 fea_imp_n=10 过于激进，元模型学不到有效模式
3. meta_1st_train_end 丢弃了大量历史数据

### 6.4 DDG-DA 后续建议

- 需要 **>=48GB 内存** 的机器才能运行 step=20 的 DDG-DA
- 或者切换到 **CSI300**（300只 vs 500只）减少约 40% 内存
- 或者使用 **DoubleAdapt** (KDD 2023) 作为替代方案（增量更新，内存需求更低）

**入口脚本**: `hats_workflows/ddgda_workflow.py`

---

## 7. Phase 2+ — 策略参数与因子优化

### 7.1 TopkDropout 参数网格搜索

基于 DoubleEnsemble Rolling (h=5, s=20) 的预测结果，测试不同 topk/n_drop 组合。

> 重要更正（2026-02-08）：`backtest_daily` 输出的 `report_normal["return"]` 为**未扣成本**收益，`report_normal["cost"]` 为**正的成本占比**；因此含成本收益应使用 `return - cost`。  
> 本节已用修正版脚本 `topk_grid_search.py` 重新回测并更新结果（含静态池/动态池两套口径），并与 Phase 2 中 `PortAnaRecord` 的 mlflow 指标口径对齐。

**度量口径（与 Qlib `PortAnaRecord` 对齐）**:
- 年化收益(含成本) = annualized_return( `return - cost` )
- 基准收益 = annualized_return( `bench` )
- 超额(含成本) = annualized_return( `return - cost - bench` )
- 超额(无成本) = annualized_return( `return - bench` )
- IR / MaxDD = `return - cost - bench` 的 information_ratio / max_drawdown

**搜索空间**:
- topk: [20, 30, 50, 80]
- n_drop: [2, 3, 5, 10, 15]
- 约束: n_drop < topk/2
- 换手率 = 2 × n_drop / topk

#### 7.1.1 静态池（market=csi500，历史对照，存在幸存者偏差）

**预测文件**: `/tmp/mlruns/461657540842089125/f078055553c84cd481e0d0845d158ec7/artifacts/pred.pkl`（DoubleEnsemble Rolling, h=5, s=20, conf=`workflow_config_rolling_double_ensemble.yaml`）  
**输出目录**: `/tmp/hats_phase2plus_topk_static_fixmetrics_20260208_142925/`（`results.csv`, `run.log`）

| topk | n_drop | turnover | E[hold] (day) | 年化收益(含成本) | 基准收益 | 超额(含成本) | 超额(无成本) | IR | MaxDD |
|------|--------|----------|---------------|------------------|---------|-------------|-------------|----|-------|
| 20 | 2 | 20% | 10.0 | 50.8% | 36.3% | 14.5% | 19.3% | 1.22 | -16.6% |
| 20 | 3 | 30% | 6.7 | 54.6% | 36.3% | 18.3% | 25.4% | 1.44 | -12.3% |
| 20 | 5 | 50% | 4.0 | 50.9% | 36.3% | 14.6% | 26.3% | 1.21 | -15.9% |
| 30 | 2 | 13% | 15.0 | 50.4% | 36.3% | 14.0% | 17.3% | 1.40 | -14.2% |
| 30 | 3 | 20% | 10.0 | 54.1% | 36.3% | 17.8% | 22.6% | 1.71 | -10.0% |
| 30 | 5 | 33% | 6.0 | 50.1% | 36.3% | 13.8% | 21.7% | 1.39 | -12.7% |
| 30 | 10 | 67% | 3.0 | 47.3% | 36.3% | 11.0% | 26.5% | 1.04 | -15.2% |
| 50 | 2 | 8% | 25.0 | 52.9% | 36.3% | 16.6% | 18.6% | 2.08 | -5.8% |
| 50 | 3 | 12% | 16.7 | 55.8% | 36.3% | 19.5% | 22.4% | 2.31 | -8.6% |
| 50 | 5 (baseline) | 20% | 10.0 | 48.5% | 36.3% | 12.2% | 17.0% | 1.48 | -9.4% |
| 50 | 10 | 40% | 5.0 | 45.4% | 36.3% | 9.1% | 18.6% | 1.08 | -12.2% |
| 50 | 15 | 60% | 3.3 | 41.4% | 36.3% | 5.1% | 19.2% | 0.60 | -14.8% |
| 80 | 2 | 5% | 40.0 | 49.8% | 36.3% | 13.4% | 14.7% | 1.90 | -6.2% |
| 80 | 3 | 8% | 26.7 | 55.7% | 36.3% | 19.4% | 21.2% | 2.69 | -5.5% |
| 80 | 5 | 12% | 16.0 | 49.3% | 36.3% | 12.9% | 16.0% | 1.75 | -8.4% |
| 80 | 10 | 25% | 8.0 | 44.6% | 36.3% | 8.3% | 14.2% | 1.14 | -9.9% |
| 80 | 15 | 38% | 5.3 | 43.6% | 36.3% | 7.3% | 16.1% | 0.97 | -12.8% |

观察（静态池，仅供对照）：
- 高换手策略在静态池下仍能保持较高超额（例如 topk=30,n_drop=10），但该口径存在幸存者偏差；不作为后续主线决策依据。

#### 7.1.2 动态池（market=csi500_dyn，主线，2026-02-08）

**预测文件**: `/tmp/hats_phase2_rolling_dyn_20260208_092935/mlruns/554786791812278150/7c48411411534a879734b49de5a12b26/artifacts/pred.pkl`（DoubleEnsemble Rolling, h=5, s=20, conf=`workflow_config_rolling_double_ensemble_dyn.yaml`）  
**输出目录**: `/tmp/hats_phase2plus_topk_dyn_fixmetrics_20260208_142537/`（`results.csv`, `run.log`）

| topk | n_drop | turnover | E[hold] (day) | 年化收益(含成本) | 基准收益 | 超额(含成本) | 超额(无成本) | IR | MaxDD |
|------|--------|----------|---------------|------------------|---------|-------------|-------------|----|-------|
| 20 | 2 | 20% | 10.0 | 49.0% | 36.3% | 12.7% | 17.6% | 1.11 | -14.3% |
| 20 | 3 | 30% | 6.7 | 44.2% | 36.3% | 7.9% | 15.0% | 0.68 | -18.5% |
| 20 | 5 | 50% | 4.0 | 42.7% | 36.3% | 6.4% | 18.2% | 0.57 | -14.9% |
| 30 | 2 | 13% | 15.0 | 43.9% | 36.3% | 7.6% | 10.8% | 0.74 | -15.3% |
| 30 | 3 | 20% | 10.0 | 41.1% | 36.3% | 4.8% | 9.6% | 0.46 | -15.6% |
| 30 | 5 | 33% | 6.0 | 42.4% | 36.3% | 6.0% | 13.9% | 0.58 | -12.4% |
| 30 | 10 | 67% | 3.0 | 36.6% | 36.3% | 0.2% | 15.7% | 0.02 | -17.5% |
| 50 | 2 | 8% | 25.0 | 47.1% | 36.3% | 10.8% | 12.8% | 1.13 | -11.7% |
| 50 | 3 | 12% | 16.7 | 42.9% | 36.3% | 6.6% | 9.5% | 0.71 | -13.0% |
| 50 | 5 (baseline) | 20% | 10.0 | 40.9% | 36.3% | 4.6% | 9.4% | 0.48 | -12.9% |
| 50 | 10 | 40% | 5.0 | 37.5% | 36.3% | 1.2% | 10.6% | 0.13 | -15.3% |
| 50 | 15 | 60% | 3.3 | 31.2% | 36.3% | -5.2% | 8.8% | -0.56 | -18.1% |
| 80 | 2 | 5% | 40.0 | 43.5% | 36.3% | 7.2% | 8.4% | 0.84 | -8.5% |
| 80 | 3 | 8% | 26.7 | 46.5% | 36.3% | 10.1% | 12.0% | 1.16 | -8.7% |
| 80 | 5 | 12% | 16.0 | 41.3% | 36.3% | 4.9% | 8.0% | 0.58 | -10.4% |
| 80 | 10 | 25% | 8.0 | 38.2% | 36.3% | 1.9% | 7.9% | 0.22 | -11.1% |
| 80 | 15 | 38% | 5.3 | 35.9% | 36.3% | -0.4% | 8.5% | -0.05 | -14.5% |

**关键发现（动态池，coarse grid：topk>=20）**:
1. **粗网格最优超额(含成本)**：topk=20, n_drop=2 → 12.7%, IR=1.11（turnover=20%，E[hold]≈10d）
2. **低换手在粗网格里更稳健**：turnover=5%~20% 的组合整体更强；高换手（>=40%）在该成本假设下收益显著衰减，甚至转负（例如 topk=50,n_drop=15）
3. **注意：粗网格缺少 small-topk/n_drop=1**：上述结论不覆盖 `topk<20` 与 `n_drop=1`；扩展搜索后发现**小 topk（更集中）能显著提升成本后超额**，且能满足“持有<10天”的短线约束（见 7.1.3）
4. **与 Phase 2 指标一致性**：baseline topk=50,n_drop=5 的超额(含成本)=4.6%、IR=0.48、MaxDD=-12.9% 与 Rolling 记录完全一致（验证本节度量口径正确）

**脚本**: `hats_workflows/topk_grid_search.py`

#### 7.1.3 动态池扩展搜索（small topk + 部署假设，2026-02-08）

背景：我们真正的短线波段目标是“持有 <10 天（平均≈5 天）”，而 coarse grid（topk>=20 且 n_drop>=2）会系统性地错过：
- `n_drop=1`（低换手/更接近“少量换仓”的做法）
- `topk<20`（更集中，适配 200,000 资金规模 + 100 股取整）

因此在同一份 DoubleEnsemble rolling 预测上，对 `topk∈{5,6,8,10,12,15,18,20}`、`n_drop∈{1..6}` 做扩展搜索，并分别用两种成交价假设对照：
- `deal_price=close`（与官方 benchmark 口径一致，偏“收盘调仓”）
- `deal_price=open`（更贴近实盘：T 日收盘后出信号，T+1 开盘成交）

公共设定：
- market: `csi500_dyn`
- backtest: 2025-01-01 ~ 2026-01-30
- account: 200,000 RMB
- benchmark: SH000905
- cost: open_cost=0.0005, close_cost=0.0015, min_cost=5
- 预测文件：同 7.1.2（`pred.pkl` 路径不变）

复现命令（建议在 `/tmp` 运行）：
```bash
cd /tmp

# deal_price=close
python /home/tanlu/myworkspace/qlib/hats_workflows/topk_grid_search.py \
  --pred_path /tmp/hats_phase2_rolling_dyn_20260208_092935/mlruns/554786791812278150/7c48411411534a879734b49de5a12b26/artifacts/pred.pkl \
  --account 200000 \
  --deal_price close \
  --topk_list 5,6,8,10,12,15,18,20 \
  --n_drop_list 1,2,3,4,5,6 \
  --output_csv /tmp/hats_phase2plus_topk_dyn_DE_h5_s20_focus_small_20260208_152809/results.csv | tee /tmp/hats_phase2plus_topk_dyn_DE_h5_s20_focus_small_20260208_152809/run.log

# deal_price=open（更贴近实盘）
python /home/tanlu/myworkspace/qlib/hats_workflows/topk_grid_search.py \
  --pred_path /tmp/hats_phase2_rolling_dyn_20260208_092935/mlruns/554786791812278150/7c48411411534a879734b49de5a12b26/artifacts/pred.pkl \
  --account 200000 \
  --deal_price open \
  --topk_list 5,6,8,10,12,15,18,20 \
  --n_drop_list 1,2,3,4,5,6 \
  --output_csv /tmp/hats_phase2plus_topk_dyn_DE_h5_s20_open_focus_small_20260208_153518/results.csv | tee /tmp/hats_phase2plus_topk_dyn_DE_h5_s20_open_focus_small_20260208_153518/run.log
```

**A) deal_price=close（small-topk focus）**  
输出目录：`/tmp/hats_phase2plus_topk_dyn_DE_h5_s20_focus_small_20260208_152809/`（`results.csv`, `run.log`）

Top 12（按超额含成本降序）：
| topk | n_drop | turnover | E[hold] (day) | 年化收益(含成本) | 基准收益 | 超额(含成本) | 超额(无成本) | IR | MaxDD |
|------|--------|----------|---------------|------------------|---------|-------------|-------------|----|-------|
| 5 | 1 | 40% | 5.0 | 88.5% | 36.3% | 52.2% | 61.8% | 2.36 | -29.3% |
| 8 | 1 | 25% | 8.0 | 86.5% | 36.3% | 50.1% | 56.2% | 2.70 | -10.5% |
| 12 | 1 | 17% | 12.0 | 79.4% | 36.3% | 43.0% | 47.1% | 2.78 | -8.7% |
| 6 | 1 | 33% | 6.0 | 77.4% | 36.3% | 41.1% | 49.0% | 2.00 | -25.6% |
| 10 | 1 | 20% | 10.0 | 76.1% | 36.3% | 39.7% | 44.6% | 2.46 | -9.5% |
| 6 | 2 | 67% | 3.0 | 75.0% | 36.3% | 38.7% | 54.1% | 2.10 | -23.5% |
| 15 | 1 | 13% | 15.0 | 72.3% | 36.3% | 36.0% | 39.3% | 2.57 | -7.3% |
| 5 | 2 | 80% | 2.5 | 70.3% | 36.3% | 34.0% | 52.3% | 1.68 | -28.0% |
| 18 | 1 | 11% | 18.0 | 68.2% | 36.3% | 31.9% | 34.6% | 2.46 | -7.8% |
| 20 | 1 | 10% | 20.0 | 67.3% | 36.3% | 31.0% | 33.5% | 2.47 | -6.6% |
| 8 | 2 | 50% | 4.0 | 61.9% | 36.3% | 25.5% | 37.3% | 1.59 | -24.8% |
| 12 | 3 | 50% | 4.0 | 56.3% | 36.3% | 20.0% | 31.7% | 1.51 | -19.1% |

**B) deal_price=open（部署口径，small-topk focus）**  
输出目录：`/tmp/hats_phase2plus_topk_dyn_DE_h5_s20_open_focus_small_20260208_153518/`（`results.csv`, `run.log`）

Top 12（按超额含成本降序）：
| topk | n_drop | turnover | E[hold] (day) | 年化收益(含成本) | 基准收益 | 超额(含成本) | 超额(无成本) | IR | MaxDD |
|------|--------|----------|---------------|------------------|---------|-------------|-------------|----|-------|
| 8 | 1 | 25% | 8.0 | 76.9% | 36.3% | 40.6% | 46.6% | 2.22 | -7.4% |
| 12 | 1 | 17% | 12.0 | 68.0% | 36.3% | 31.6% | 35.7% | 2.10 | -10.2% |
| 6 | 1 | 33% | 6.0 | 67.8% | 36.3% | 31.4% | 39.3% | 1.57 | -17.5% |
| 15 | 1 | 13% | 15.0 | 67.6% | 36.3% | 31.3% | 34.6% | 2.23 | -6.7% |
| 10 | 1 | 20% | 10.0 | 67.3% | 36.3% | 30.9% | 35.8% | 1.92 | -9.9% |
| 5 | 1 | 40% | 5.0 | 65.1% | 36.3% | 28.7% | 38.2% | 1.30 | -29.2% |
| 18 | 1 | 11% | 18.0 | 63.2% | 36.3% | 26.8% | 29.5% | 2.06 | -7.2% |
| 20 | 1 | 10% | 20.0 | 60.2% | 36.3% | 23.8% | 26.4% | 1.91 | -7.8% |
| 6 | 2 | 67% | 3.0 | 51.5% | 36.3% | 15.2% | 30.6% | 0.83 | -24.4% |
| 12 | 3 | 50% | 4.0 | 50.9% | 36.3% | 14.6% | 26.3% | 1.05 | -17.0% |
| 18 | 4 | 44% | 4.5 | 49.5% | 36.3% | 13.2% | 23.7% | 1.07 | -9.1% |
| 8 | 2 | 50% | 4.0 | 48.7% | 36.3% | 12.4% | 24.1% | 0.76 | -18.7% |

观察（扩展搜索的结论修正）：
- **“高换手必然吞噬 alpha”并不成立**：在 small-topk（更集中）下，即便 turnover≈25%~40% 仍可能实现很高的成本后超额；决定性因素更像是“集中度(topk) + n_drop（换手） + 信号强度”的共同作用
- **部署口径推荐（当前窗口最优 & 持有<10天）**：`deal_price=open` + `topk=8,n_drop=1` → 超额(含成本)=40.6%，IR=2.22，MaxDD=-7.4%（E[hold]≈8d）
- **若强约束 E[hold]≈5 天**：`topk=5,n_drop=1` 虽满足持有≈5天，但回撤显著增大（MaxDD≈-29%）；建议先用 `topk=8,n_drop=1` 作为可部署基线，再评估是否要进一步缩短持有期
- **实战一致性检查（涨跌停交易方向）**：用 `--allow_trade_at_limit`（即 `forbid_all_trade_at_limit=false`，允许“涨停卖出/跌停买入”）复跑 open 口径，结果与本节表格**完全一致**（该窗口下限制条件对结果不敏感）。输出目录：`/tmp/hats_phase2plus_topk_dyn_DE_h5_s20_open_focus_small_allowlimit_20260209_054900/`
- **数据质量提醒（open 成交）**：`deal_price=open` 回测时出现 `$open field data contains nan` warning（见 run.log）；需确认 open 字段缺失是否仅来自停牌/上市首日等可解释原因，并确保策略在 open 缺失时的处理逻辑与实盘一致

### 7.2 Alpha158PlusCustom 164因子实验

使用自定义 handler Alpha158PlusCustom，在 Alpha158 基础上增加 6 个 HATS 自定义因子：
- alpha_adx_trend, alpha_boll_position, alpha_cci_extreme
- alpha_macd_hist, alpha_rsi_divergence, alpha_winner_rate

**配置**: DoubleEnsemble Rolling, h=5, s=20（与最优基线相同，仅替换 handler）
**配置文件**: `workflow_config_rolling_de_164.yaml`
**运行时间**: ~4.7 小时

| 指标 | Alpha158 (158因子) | Alpha158PlusCustom (164因子) | 变化 |
|------|-------------------|------------------------------|------|
| IC | 0.0426 | 0.0388 | -0.0038 |
| ICIR | 0.4233 | 0.3714 | -0.0519 |
| Rank IC | 0.0469 | 0.0464 | -0.0005 |
| Rank ICIR | 0.4907 | 0.4510 | -0.0397 |
| 超额(含成本) | 12.2% | 12.5% | +0.3% |
| IR | 1.48 | 1.40 | -0.08 |
| MaxDD | -9.4% | -10.0% | -0.6% |
| 超额(无成本) | — | 17.3% | — |

**结论**:
- 6个自定义因子对模型贡献极有限：Rank IC 几乎不变（0.0469→0.0464）
- 超额收益微增（12.2%→12.5%），但 ICIR 和 MaxDD 略有恶化
- **Alpha158 已覆盖大部分有效信息，自定义因子信息冗余**
- 建议：不值得为 6 个因子增加数据维护成本，继续使用 Alpha158 即可

---

## 8. 综合结果总表

> 注：本表主要汇总“短线波段（h≈5）”这条主线的历史实验结果；其中 Phase 1/2/2+ 大多是在 `market: csi500`（静态口径）下完成，存在幸存者偏差风险。  
> `benchmarks_dynamic` 的 RR baseline 对齐（h=20,s=20，2017-2020）已单独记录在 Phase 0。

| Phase | 实验 | 模型 | h | s | Rank IC | Rank ICIR | 年化超额 | IR | MaxDD |
|-------|------|------|---|---|---------|-----------|---------|-----|-------|
| 1 | Static T+1 | LightGBM | 1 | - | 0.0244 | 0.1205 | - | - | - |
| 1 | Static T+1 (dyn) | LightGBM | 1 | - | 0.0320 | 0.1476 | -32.3% | -2.00 | -24.8% |
| 1 | Static T+3 | LightGBM | 3 | - | 0.0261 | 0.1320 | - | - | - |
| 1 | Static T+3 (dyn) | LightGBM | 3 | - | 0.0285 | 0.1379 | -33.4% | -2.17 | -23.8% |
| 1 | Static T+5 | LightGBM | 5 | - | 0.0216 | 0.1094 | - | - | - |
| 1 | Static T+5 (dyn) | LightGBM | 5 | - | 0.0213 | 0.1023 | -32.2% | -2.07 | -23.1% |
| 1 | Static T+10 | LightGBM | 10 | - | 0.0118 | 0.0620 | - | - | - |
| 1 | Static T+10 (dyn) | LightGBM | 10 | - | -0.0029 | -0.0141 | -33.2% | -2.24 | -24.4% |
| 2 | Rolling | LightGBM | 1 | 20 | 0.0180 | 0.1730 | 16.1% | 1.23 | -14.7% |
| 2 | Rolling | LightGBM | 3 | 20 | 0.0341 | 0.3439 | 8.0% | 0.82 | -13.2% |
| **2** | **Rolling** | **LightGBM** | **5** | **20** | **0.0463** | **0.5106** | **7.1%** | **0.83** | **-12.5%** |
| 2 | Rolling | LightGBM | 10 | 20 | 0.0470 | 0.5018 | 1.0% | 0.11 | -14.2% |
| 2 | Rolling | LightGBM | 5 | 10 | 0.0445 | 0.4794 | 7.3% | 0.88 | -11.6% |
| 2 | Rolling | LightGBM | 5 | 5 | 0.0404 | 0.4308 | 3.2% | 0.37 | -15.1% |
| 2 | Rolling (dyn) | LightGBM | 1 | 20 | 0.0175 | 0.1871 | 6.8% | 0.85 | -12.1% |
| 2 | Rolling (dyn) | LightGBM | 3 | 20 | 0.0321 | 0.3441 | -0.7% | -0.08 | -15.1% |
| 2 | Rolling (dyn) | LightGBM | 5 | 20 | 0.0430 | 0.4768 | 2.0% | 0.19 | -12.9% |
| 2 | Rolling (dyn) | LightGBM | 10 | 20 | 0.0475 | 0.5252 | 0.4% | 0.04 | -15.9% |
| 2 | Rolling (dyn) | LightGBM | 5 | 10 | 0.0418 | 0.4628 | -0.4% | -0.04 | -13.3% |
| 2 | Rolling (dyn) | LightGBM | 5 | 5 | 0.0432 | 0.4819 | 4.6% | 0.44 | -10.7% |
| 2 | Rolling | XGBoost | 5 | 20 | 0.0399 | 0.4822 | 16.5% | 1.97 | -10.7% |
| 2 | Rolling (dyn) | XGBoost | 5 | 20 | 0.0438 | 0.5591 | 9.8% | 1.41 | -5.5% |
| 2 | Rolling | Linear | 5 | 20 | 0.0424 | 0.4513 | 2.4% | 0.25 | -14.2% |
| 2 | Rolling (dyn) | Linear | 5 | 20 | 0.0420 | 0.4035 | -5.7% | -0.49 | -17.0% |
| **2** | **Rolling** | **DoubleEnsemble** | **5** | **20** | **0.0469** | **0.4907** | **12.2%** | **1.48** | **-9.4%** |
| 2 | Rolling (dyn) | DoubleEnsemble | 5 | 20 | 0.0482 | 0.5052 | 4.6% | 0.48 | -12.9% |
| 2+ | TopkOpt (dyn, close, topk=8,n_drop=1, acct=200k) | DoubleEnsemble | 5 | 20 | 0.0482 | 0.5052 | 50.1% | 2.70 | -10.5% |
| **2+** | **TopkOpt (dyn, open, topk=8,n_drop=1, acct=200k)** | **DoubleEnsemble** | **5** | **20** | **0.0482** | **0.5052** | **40.6%** | **2.22** | **-7.4%** |
| 2+ | Rolling 164因子 | DoubleEnsemble | 5 | 20 | 0.0464 | 0.4510 | 12.5% | 1.40 | -10.0% |
| 3 | DDG-DA (s=40) | LightGBM | 5 | 40 | 0.0421 | 0.4178 | 0.2% | 0.02 | -16.9% |
| 3 | DDG-DA (s=20) | LightGBM | 5 | 20 | _(OOM×3)_ | | 30GB不足 | | |

---

## 9. 关键发现

1. **CSI500 必须使用动态成分（先 1 后 2）**：静态 `csi500` 会导致历史区间可用成分数显著 <500，并引入幸存者偏差；已落盘 `csi500_dyn` 并完成 RR baseline 对齐验证（见 Phase 0）
2. **静态训练（即便换成动态池）仍不可用**：Phase 1 重跑后 Rank IC 最高 0.032（远低于 0.045），且成本后超额收益为负（见 Phase 1.4）
3. **Rolling Retrain 是核心提升（动态池已初步验证）**：在 `csi500_dyn` 下 rolling 可把 Rank IC 提升到 ~0.048（优于静态训练），并在部分配置下实现正的成本后超额收益（见 Phase 2.8）
4. **horizon 存在“信号质量 vs 收益”权衡**：在动态池测试期内，h=10 的 Rank IC 更高但收益更低；h=1 收益更高但 Rank IC 较低；h=5 仍是更稳健的折中候选（需进一步验证）
5. **step 需要重新评估（动态池与静态池结论不一致）**：在动态池测试期内，h=5 时 `step=5` 的组合收益/回撤优于 `step=20`，但训练成本显著上升（53 tasks）；需要更多窗口验证后再定
6. **模型主线选择（按当前研究决策）**：后续只保留 **LightGBM + DoubleEnsemble**
   - Linear/XGBoost 已完成一次对照与 sanity check；**不再投入算力优化**
   - DoubleEnsemble 在动态池下 Rank IC 仍最强（≈0.048），收益更依赖 step 与 TopkDropout/成本假设（见 Phase 5.8 与 7.1.2/7.1.3）
7. **DDG-DA 在 30GB 机器上不可行**：CSI500 + step=20 需要 ~20GB RSS，超出可用内存
8. **DDG-DA step=40 妥协方案性能不佳**：全面劣于 plain Rolling step=20
9. **TopkDropout 策略是“收益放大器”（必须做 small-topk 扩展搜索）**：
    - coarse grid（topk>=20）下最优仅 12.7%（topk=20,n_drop=2），容易误判“高换手必然不行”（见 Phase 7.1.2）
    - 扩展到 small-topk + `n_drop=1` 后，DoubleEnsemble 在同一窗口出现显著更高的成本后超额（见 Phase 7.1.3）：
      - 部署口径（`deal_price=open`, `account=200000`）：topk=8,n_drop=1 → **40.6%**, IR=2.22, MaxDD=-7.4%（E[hold]≈8d）
      - 若强约束持有≈5天：topk=5,n_drop=1 → 28.7% 但 MaxDD≈-29%（风险显著更高）
    - 结论：换手会影响收益，但“集中度(topk)”同样关键；不要只用 topk>=20 的粗网格做决策

---

## 10. 技术备忘

### 运行环境
- Python 3.12
- Qlib (from source: `/home/tanlu/qlib_src/`)
- 运行目录: `/tmp`（避免 qlib 源码导入冲突）
- MLflow: `/tmp/mlruns/`
- 系统内存: 30GB, 无 Swap

### 常见问题
1. **`ModuleNotFoundError: No module named 'qlib.data._libs.rolling'`**: 从 qlib 源码目录运行导致 → 切换到 `/tmp` 运行
2. **`ValueError: instrument does not contain data for day`**: provider_uri 需要指向 `.../qlib_bin/` 而非 `.../cn/`
3. **DDG-DA OOM**: 不能与其他大型实验同时运行，需减少 hist_step_n 和 fea_imp_n
4. **Rolling 不读取 YAML 的 `qlib_init`**: 需要外部 `auto_init/qlib.init` 明确指定数据源 provider_uri
5. **handler cache 串数据（跨 provider）**: `Alpha158.<hash>.pkl` 的 hash 不包含 provider_uri → 不同数据源需隔离 conf 目录或显式指定 cache 路径
6. **instruments 代码大小写不一致**: crowd instruments 常为 `SH/SZ`，自建 features 目录为 `sh/sz` → instruments 需大小写适配
7. **`day_future.txt` 缺失 warning**: 自建数据缺少 future calendar 时可能出现提示；历史回测通常不致命，但需注意依赖 future 日历的流程

### 文件结构
```
hats_workflows/
├── EXPERIMENT_LOG.md                           # 本文件 — 实验记录
├── config_train.yaml                           # 静态训练配置
├── config_predict.yaml                         # 预测配置（HATS 部署模型路径）
├── custom_handler.py                           # Alpha158PlusCustom（164因子）
├── run_workflow.py                             # 静态训练入口
├── signal_duckdb_pipeline.py                   # 预测/指令/成交/对账 DuckDB 管道
├── auto_signal_scheduler.py                    # qlib 侧自动化编排（daily/reconcile）
├── rolling_benchmark.py                        # Rolling 训练入口
├── ddgda_workflow.py                           # DDG-DA 入口
├── topk_grid_search.py                         # TopkDropout 参数网格搜索
├── workflow_config_rolling_lgbm.yaml           # Rolling LightGBM 配置
├── workflow_config_rolling_lgbm_dyn.yaml       # Rolling LightGBM 配置（动态池）
├── workflow_config_rolling_xgboost.yaml        # Rolling XGBoost 配置
├── workflow_config_rolling_xgboost_dyn.yaml    # Rolling XGBoost 配置（动态池）
├── workflow_config_rolling_linear.yaml         # Rolling Linear 配置
├── workflow_config_rolling_linear_dyn.yaml     # Rolling Linear 配置（动态池）
├── workflow_config_rolling_double_ensemble.yaml # Rolling DoubleEnsemble 配置
├── workflow_config_rolling_double_ensemble_dyn.yaml # Rolling DoubleEnsemble 配置（动态池）
├── workflow_config_rolling_double_ensemble_dyn_deploy.yaml # Rolling DoubleEnsemble 配置（动态池，部署口径：open/topk=8/n_drop=1/acct=200k）
├── workflow_config_rolling_de_164.yaml         # Rolling DoubleEnsemble 164因子配置
├── workflow_config_rolling_de_164_dyn.yaml     # Rolling DoubleEnsemble 164因子配置（动态池）
├── configs/
│   ├── phase1_lgbm_label_t1.yaml
│   ├── phase1_lgbm_label_t1_dyn.yaml
│   ├── phase1_lgbm_label_t3.yaml
│   ├── phase1_lgbm_label_t3_dyn.yaml
│   ├── phase1_lgbm_label_t5.yaml
│   ├── phase1_lgbm_label_t5_dyn.yaml
│   ├── phase1_lgbm_label_t10.yaml
│   ├── phase1_lgbm_label_t10_dyn.yaml
│   └── phase1_lgbm_alpha158_plus.yaml
└── models/current/
```

### 相关报告与基线对齐材料（建议也当作实验记录的一部分）
- 短线波段研究设计（论文式交付）：`examples/csi500_swing5d/RESEARCH_REPORT.md`
- `benchmarks_dynamic` RR 基线对齐（自建数据 vs crowd 数据）：`examples/benchmarks_dynamic/csi500_rr_compare/RR_BENCHMARK_COMPARISON.md`
- RR 对比指标 JSON 归档：`examples/benchmarks_dynamic/csi500_rr_compare/run_outputs/`

---

## 11. HATS 自动化部署联调（2026-02-10）

### 11.1 目标

- `qlib` 持续研究与周期训练，`HATS` 执行每日预测与落库。
- 周期训练出的最新模型自动部署到 `HATS/models/qlib_deployed_current.pkl`。
- 每日把预测信号与执行成交写入 DuckDB，形成可对账闭环。

### 11.2 已落地链路

- HATS 入口脚本：`/home/tanlu/myworkspace/HATS/scripts/daily_signal_scheduler.py`
  - `run-daily`：调用 HATS 本地预测编排并落库（`qlib_predictions` / `qlib_orders`）
  - `run-reconcile`：导入成交并对账（`qlib_executions` / `qlib_reconcile`）
  - `run-retrain-deploy`：周期训练（可选）+ 模型部署 + 历史记录
- HATS 本地预测管道脚本（与 qlib 仓调度解耦）：
  - `/home/tanlu/myworkspace/HATS/scripts/auto_signal_scheduler.py`
  - `/home/tanlu/myworkspace/HATS/scripts/signal_duckdb_pipeline.py`
  - `/home/tanlu/myworkspace/HATS/scripts/qlib_workflow.py`
- 模型部署产物：
  - 当前线上模型软链：`/home/tanlu/myworkspace/HATS/models/qlib_deployed_current.pkl`
  - 部署历史：`/home/tanlu/myworkspace/HATS/models/qlib_deploy_history.jsonl`

### 11.3 定时任务（当前生效）

- `40 19 * * 1-5`：每日预测落库（Asia/Shanghai）
- `10 20 * * 1-5`：每日执行对账（Asia/Shanghai）
- 注：生产 cron 当前按“研究与生产分离”原则，仅保留每日预测/对账；重训部署改为人工或 qlib 研究侧触发后发布模型。

### 11.4 联调结果（本次）

- `run-retrain-deploy --skip-train`：成功，部署历史追加，软链指向当前模型。
- `run-daily --date 2026-02-09`：成功。
  - `qlib_predictions`（signal_date=2026-02-09, model=lgbm_csi1000_20260130_qlib）：5169 行，`is_selected=8`
  - `qlib_orders`（trade_date=2026-02-10）：8 行（BUY=8）
- `run-reconcile --date 2026-02-10`：成功（无成交文件时按非严格模式跳过）。
- 生产参数决策更新（2026-02-10）：
  - 股票池：`csi500_dyn`（先按动态成分运行，后续可切换）
  - 推理范围：直接在 `csi500_dyn` 上推理（不再全市场后过滤）
  - 交易参数：`topk=8, n_drop=1`（先沿用当前高收益口径）
  - 验证：`signal_date=2026-02-09` 预测入库 500 行、`is_selected=8`、订单 8 行

### 11.5 问题与修复

1) **问题：对账顺序 bug（自动化稳定性）**  
   - 现象：`run-reconcile` 在检查执行文件前先推断 `model_name`，导致“无成交文件时本应跳过”却报错。  
   - 修复：调整 `/home/tanlu/myworkspace/HATS/scripts/auto_signal_scheduler.py` 顺序，先检查执行文件，再推断模型并执行对账。

2) **问题：预测日期超出当前 qlib 日历时会触发处理器空样本报错**  
   - 现象：`run-daily --date 2026-02-10` 在当前日历仅到 2026-02-09 时触发 `ZeroDivisionError`。  
   - 结论：生产运行需确保 `daily_qlib_update` 已把当日交易日写入 qlib 日历后再触发预测（当前 cron 已按“数据更新 -> 预测”顺序配置）。

3) **问题：`csi500_dyn` 末端日期滞后会导致预测股票池为空**  
   - 现象：`csi500_dyn.txt` 末端曾停在 2026-02-06，而日历已到 2026-02-09。  
   - 修复：在 `HATS/scripts/daily_qlib_update.py` 增加 `extend_instruments_tail`，每日把 `csi500_dyn.txt` 的末端区间自动延长到最新交易日。

### 11.6 生产切换：线上模型切到 `csi500_dyn`（2026-02-10）

- 训练：`qlib/hats_workflows/run_workflow.py --mode train --config hats_workflows/config_train_csi500_dyn.yaml`
  - 产物：`/home/tanlu/myworkspace/qlib/hats_workflows/models/lgbm_csi500_dyn_20260210.pkl`
  - 训练日志关键指标：Rank IC ≈ 0.0295
- 部署：`HATS/scripts/daily_signal_scheduler.py run-retrain-deploy --skip-train --model-source .../lgbm_csi500_dyn_20260210.pkl`
  - 线上软链切换为：`/home/tanlu/myworkspace/HATS/models/qlib_deployed_current.pkl -> lgbm_csi500_dyn_20260210_qlib.pkl`
- 验证（signal_date=2026-02-09）：
  - `qlib_predictions`：500 行，`is_selected=8`
  - `qlib_orders`：8 行（BUY=8）

### 11.7 生产调度重构（DoubleEnsemble 主线，2026-02-10）

目标：停用会干扰当前主线的旧训练任务，并把生产定时任务切到 `csi500_dyn + DoubleEnsemble` 口径。

本次变更：
- 已从用户 `tanlu` 的 crontab 删除旧月度任务：`rolling_train_standard.py ... --market csi1000`
- HATS 自动块（`# >>> hats_auto_signal_in_hats >>>`）新增月度重训部署：
  - `30 20 1-7 * 6 ... daily_signal_scheduler.py run-retrain-deploy --train-runner hats --train-config /home/tanlu/myworkspace/HATS/configs/qlib_train_de_csi500_dyn.yaml ...`
- `daily_signal_scheduler.py` 改造：
  - `run-retrain-deploy` 支持 `--train-runner hats|qlib`（默认 `hats`）
  - 默认训练配置改为 `HATS/configs/qlib_train_de_csi500_dyn.yaml`
  - 部署历史增加 `train_runner` 字段，便于审计
- `HATS/scripts/qlib_workflow.py` 改造：
  - 训练配置兼容 `model_config/dataset_config` 与 `task.model/task.dataset`
  - 模型名按模型类型自动命名（如 `doubleensemble_*` / `lgbm_*`）
  - 训练评估优先按 `segment=test` 预测，避免全量预测带来的额外开销
- `HATS/configs/qlib_predict_deployed.yaml` 标签口径对齐为 5 日：`Ref($close, -6) / Ref($close, -1) - 1`

发现的问题与修复：
1) **旧月度 csi1000 训练仍在运行，和主线口径冲突**  
   - 风险：模型池被非主线训练覆盖，影响后续部署一致性。  
   - 处理：删除该 cron 行，只保留 HATS 自动块内的调度。
2) **`run-retrain-deploy --skip-train` 在 HATS 无 `models/current` 时可能失败**  
   - 现象：历史部署模型仅有 `qlib_deployed_current.pkl`，无 `current`。  
   - 修复：`daily_signal_scheduler.py` 增加回退逻辑，优先 `models/current`，否则使用 `models/qlib_deployed_current.pkl`。

联调结果（2026-02-10）：
- `run-retrain-deploy --skip-train --train-runner hats --model-source .../lgbm_csi500_dyn_20260210_qlib.pkl`：成功，部署历史已写入。
- `run-daily --date 2026-02-09`：成功；`lgbm_csi500_dyn_20260210_qlib` 写入 `qlib_predictions` 500 行，`is_selected=8`，`qlib_orders` 8 行。

### 11.8 run-daily “有预测无订单”问题修复（2026-02-10）

问题复盘：
- 现象：`run-daily --date 2026-02-10` 生成了 500 条预测，但无新增 BUY/SELL 订单。
- 初始假设（“缺下一交易日导致无订单”）不完整；根因是订单生成逻辑未真正应用 `n_drop`。

根因分析：
1) **`TopkDropout` 语义未落地**  
   旧逻辑仅做“当前 topk 与前一日 topk 的集合差”，若集合相同则无换仓。  
   这与 `topk=8, n_drop=1` 的预期不一致（应存在受控换手）。
2) **无未来交易日时 trade_date 回退过于粗糙**  
   旧逻辑在 DuckDB 中查不到 `signal_date` 之后交易日时直接 `+1 天`，周五会落到周六，存在错配风险。

修复内容：
- 文件：`/home/tanlu/myworkspace/HATS/scripts/signal_duckdb_pipeline.py`
  - `build_orders` 改为 TopkDropout 逻辑：
    - 卖出：前持仓中不在今日 topk 的 + 额外按今日排名最差的 `n_drop`；
    - 买入：按今日分数从高到低补齐到 topk（跳过当日已卖出标的）；
    - 保证 `n_drop` 在生产下单层面真实生效。
  - `get_next_trade_date` 回退策略由“+1 天”改为“下一个工作日（跳过周末）”。

验证（同日回归）：
- 命令：`daily_signal_scheduler.py run-daily --date 2026-02-10 ...`
- 结果：
  - `qlib_predictions`：`signal_date=2026-02-10`，500 行，`is_selected=8`
  - `qlib_orders`：`signal_date=2026-02-10`，`trade_date=2026-02-11`，生成 `BUY=1, SELL=1`
  - 示例：`SELL SH600062(rank=8)` + `BUY SH600079(rank=9)`（符合 `n_drop=1` 的换手预期）

### 11.9 常数分数问题专项调查（2026-02-10 夜）

背景：你提出“是否有完整 csi500 得分”，检查发现虽然有 500 行预测，但 `score` 全部相同，排名仅由 CSV 行顺序决定。

复现实验（同一模型、同一日期，分别用旧逻辑与修复逻辑）：
- 旧逻辑（`start_time=pred_date, end_time=pred_date`）：
  - 特征行数：500
  - 唯一特征行：1
  - 有方差特征列：0
  - 预测唯一分数数：1（常数）
- 修复逻辑（保留历史 `start_time`，仅限制 `end_time=pred_date`）：
  - 特征行数：500
  - 唯一特征行：500
  - 有方差特征列：158
  - 预测唯一分数数：500（恢复区分度）

根因确认：
- 文件：`/home/tanlu/myworkspace/HATS/scripts/qlib_workflow.py`
- 旧实现在预测阶段把 `data_handler_config.start_time` 强制设为预测日，导致 Alpha158 的历史窗口特征无法计算，最终经处理器后全样本特征趋同。

修复：
- `qlib_workflow.py` 预测逻辑改为：
  - 不再覆盖 `start_time`
  - 仅将 `end_time` 设为预测日
  - 若 `fit_end_time > pred_date`，则收敛到 `pred_date`

回归结果（修复后重新跑 `signal_date=2026-02-10`）：
- `qlib_predictions`（model=`lgbm_csi500_dyn_20260210_qlib`）：
  - 500 行、500 个不同分数，分数范围约 `[-0.1722, 0.1154]`
- `qlib_orders`：
  - `trade_date=2026-02-11`，`BUY=8, SELL=8`
  - Top8 买入样本：`SH601139, SH601997, SH601577, SZ002608, SZ000728, SH600642, SH601128, SH600380`
