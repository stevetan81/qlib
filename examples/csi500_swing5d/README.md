# CSI500 短线波段（平均持有≈5天）- Qlib 配置示例

本目录给出一套“能直接跑通”的基线配置，用于 **中证500（`csi500`）** 做日频短线波段（平均持有期约 5 个交易日）的 **模型训练 + 回测闭环**。

核心思路：
- 预测 **T 日收盘后**生成信号，**T+1 日开盘**执行交易（更贴近可落地的日频流程）。
- 组合层面用 `TopkDropoutStrategy` 控制持有期（`avg_hold≈topk/n_drop`）。动态池扩展搜索显示：部署口径推荐 `topk=8,n_drop=1`（E[hold]≈8d）；严格 5 天可用 `topk=5,n_drop=1` 但回撤更大（详见 `hats_workflows/EXPERIMENT_LOG.md` 的 Phase 7.1.3）。

## 文件说明
- `RESEARCH_REPORT.md`
  - 论文式交付：更正式的研究/调研报告（侧重方法学与实验设计；包含一节用于对齐 `benchmarks_dynamic` 的 RR sanity check 结果，用来排查数据口径差异）。
- `REPORT.md`
  - 研究简版：要点版（更短、更便于快速对齐关键假设）。
- `workflow_config_lightgbm_alpha158_csi500_swing5d_open_base.yaml`
  - 适用于：你已有可用的 `cn` 数据（不要求额外字段）。
  - 限制：涨跌停按统一阈值近似（`limit_threshold: 0.095`）。
- `workflow_config_lightgbm_alpha158_csi500_swing5d_open_tushare.yaml`
  - 适用于：你用 Tushare 自建了 Qlib 数据，并额外提供了 `up_limit/down_limit/is_st` 等字段。
  - 优点：可用 **逐股逐日涨跌停价** 做限价（含 ST/20cm 等差异），并动态过滤 ST/停牌日。

## 你给定的关键参数（已体现在 YAML 里）
- 目标持有期：<10 天；目标平均约 5 天（理论上 `topk/n_drop≈5`）
  - 部署口径（当前窗口最优，见 Phase 7.1.3）：`topk: 8, n_drop: 1`（E[hold]≈8 天，turnover≈25%/日）
  - 更分散/更稳健备选：`topk: 20, n_drop: 2`（E[hold]≈10 天，turnover≈20%/日）
- 股票池：CSI500（基准 `SH000905`）
  - 如果你的 `provider_uri` 下 `instruments/csi500.txt` 是**动态成分**（例如 crowd 数据），直接用 `market: csi500` 即可；
  - 如果你的 `csi500.txt` 是**静态列表**（你自建数据的原始情况），请改用 `market: csi500_dyn`（见 `examples/benchmarks_dynamic/csi500_rr_compare/RR_BENCHMARK_COMPARISON.md`）。
- 过滤：建议过滤 ST；停牌由交易所/成交规则约束自然处理（更真实）
- 初始资金：`account: 200000`（现金太小会受 `trade_unit=100` 影响导致买不到/权重失真）

## 运行方式
1) 准备 Qlib 数据（示例默认在 `~/.qlib/qlib_data/cn_data`；你用 Tushare 自建时建议改成独立目录）。

如果你希望与 `examples/benchmarks_dynamic/` 的基线数据保持一致（推荐作为后续研究对比基准），可直接使用其 README 推荐的 crowd-sourced 数据（含 VWAP）：

```bash
wget https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz
mkdir -p ~/.qlib/qlib_data/cn_data
tar -zxvf qlib_bin.tar.gz -C ~/.qlib/qlib_data/cn_data --strip-components=2
rm -f qlib_bin.tar.gz
```

2) 生成 `csi500` instruments（如果你的数据目录里还没有）：

```bash
python scripts/data_collector/cn_index/collector.py --index_name CSI500 --qlib_dir ~/.qlib/qlib_data/cn_data --method parse_instruments
```

3) 跑基线：

```bash
qrun examples/csi500_swing5d/workflow_config_lightgbm_alpha158_csi500_swing5d_open_base.yaml
```

或（Tushare 增强版）：

```bash
qrun examples/csi500_swing5d/workflow_config_lightgbm_alpha158_csi500_swing5d_open_tushare.yaml
```

## Tushare 能拿到什么：建议先自检
用 `scripts/tushare/probe_tushare_pro.py` 以你的 `TUSHARE_TOKEN` 做最小调用自检（不会打印 token）：

```bash
export TUSHARE_TOKEN="你的token"
python scripts/tushare/probe_tushare_pro.py
```

它会探测：`daily/adj_factor/daily_basic/stk_limit/suspend_d/namechange/trade_cal/index_weight` 等接口是否可用，并给出你需要补齐字段的建议。
