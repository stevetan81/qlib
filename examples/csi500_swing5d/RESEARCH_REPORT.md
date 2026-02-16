# 基于 Qlib 的 A 股（CSI500）短线波段研究与训练设计报告（论文式交付）

版本：v1.1  
日期：2026-02-08  
对象：CSI500（`csi500`）日频短线波段（平均持有≈5天），无分钟线数据  

> 声明：本文为研究/工程设计报告，不构成任何投资建议。短线策略对交易成本、涨跌停/停牌约束与数据质量高度敏感；任何“高收益”必须以严格的样本外验证与可交易约束检验为前提。

---

## 摘要（Abstract）

本文面向 A 股中证500（CSI500）股票池，给出一套用于**短线波段（平均持有约 5 个交易日）**的量化研究与 Qlib 模型训练/回测设计框架。该框架强调“标签—成交价—回测执行假设”的一致性，并把 A 股特有的制度性摩擦（T+1、100 股最小交易单位、涨跌停、停牌）与交易成本/冲击成本纳入实验设计与评估指标。基于可获得的数据条件（Tushare Pro，缺分钟线），本文提出以 **T 日收盘后出信号、T+1 开盘成交** 为基准执行假设，采用与平均持有期一致的 open-to-open 多日标签，并推荐使用逐股逐日涨跌停价（`up_limit/down_limit`）来替代常数阈值的限价近似。最后，本文给出 walk-forward 为核心的实验矩阵（标签持有期、成本敏感性、限价规则、过滤规则、组合超参等），以支持后续高质量、可复现的 Qlib 研究迭代。

关键词：Qlib；CSI500；短线波段；涨跌停；交易成本；walk-forward；Tushare

---

## 1. 研究目标与约束（Problem Setup）

### 1.1 你的设定（输入）
- 目标持有期：小于 10 天，平均约 5 天
- 股票池：CSI500（`csi500`）
- 过滤：希望过滤 ST 与停牌（若更优）
- 数据：Tushare Pro（积分 10100），暂无分钟线
- 初始资金：200,000 RMB（如需要可调整到更小，但会受 100 股取整影响）

### 1.2 研究目标（输出）
本文交付的不是“某个模型跑出多少收益”，而是：
1) 一套**可复现的数据—标签—特征—回测—评估闭环**  
2) 一套针对短线波段的**实验矩阵与稳健性检验清单**  
3) 一套把学术结论落成可检验假设的**研究路线图**  

### 1.3 关于“跑通”的说明（避免误解）
Qlib 仓库里已经有大量现成 workflow（例如 `examples/benchmarks/`、`examples/benchmarks_dynamic/`、`examples/model_rolling/`），很多确实“一条命令就能跑通”。本文强调的“跑通”不是指 **Qlib 能不能运行**，而是指**把你的交易假设跑通并对齐**：
- 股票池从 CSI300/全市场切换到 **CSI500**（动态成分）
- 持有期从 1D/20D 切换到 **平均≈5天**（标签、组合与回测一致）
- 成交价（open/close）与 label 定义一致（避免“标签与回测不一致”的隐性前视）
- 涨跌停/停牌/100股/成本冲击等约束被纳入评估（否则回测高收益常不可交易）

---

## 2. 研究问题与可检验假设（Research Questions & Hypotheses）

为避免“回测优化即过拟合”，建议先把研究拆成可证伪问题：

**RQ1：CSI500 在 2–10 日持有期是否存在稳定横截面可预测性？**  
H1：在加入交易成本/限价/停牌/交易单位约束后，仍存在稳定的 RankIC 与成本后超额收益。

**RQ2：涨跌停制度对短线“可预测性 vs 可交易性”的影响有多大？**  
H2：用逐股逐日 `up_limit/down_limit` 的限价规则替代常数阈值后，策略表现显著更接近可实现水平，且回测的“异常高收益”会明显收敛。

**RQ3：换手/流动性状态是否调制短线动量/反转？**  
H3：按换手率/成交额分组后，短期动量与短期反转的强弱会显著不同（状态依赖）。

**RQ4：风险过滤能否提升成本后稳定性？**  
H4：在相同预测信号下，加入波动/跳空风险过滤可降低回撤并提升成本后收益的稳健性（尤其在高波动阶段）。

---

## 3. 市场结构与制度性约束（China A-share Microstructure Constraints）

短线研究必须内生化以下约束，否则回测收益往往不可交易：

### 3.1 T+1
日频研究通常默认：T 日收盘后形成信号 → T+1 执行（至少避免“当天收盘价生成信号又当天成交”的前视偏差）。

### 3.2 交易单位（`trade_unit=100`）
买入股数会按最小单位取整。资金较小、`topk` 过大时会出现大量“买不到（取整为 0）”并导致回测失真。

### 3.3 涨跌停与不可成交
涨跌停会导致“信号正确但买不到/卖不出”，短线策略对这一点极其敏感。工程上建议：
- 不写死阈值（如 0.095/0.1），而是使用数据源提供的逐股逐日涨跌停价 `up_limit/down_limit`
- 将“不可成交比例/被动持仓天数”作为核心评估输出（而非只看年化）

### 3.4 停牌
停牌属于真实风险，应在回测中体现“无法交易、被动持仓”的现实。更合理的做法是：
- 下单时仅对可交易标的下单（`only_tradable`）
- 统计停牌造成的“无法卖出天数/资金占用”

---

## 4. 数据与样本构建（Data & Universe）

### 4.1 建议的数据字段规范（落成 Qlib bin）

**必需字段（最小可用）**
- `open/high/low/close/volume/factor`

**短线强烈建议字段（可交易性关键）**
- `amount`：成交额（流动性与 vwap 近似）
- `up_limit/down_limit`：逐股逐日涨跌停价（用于限价规则）
- `is_st`：逐日 ST 标记（用于过滤）

**可选增强字段（用于“状态依赖”建模）**
- `turnover_rate/turnover_rate_f/float_mv/total_mv`（`daily_basic`）

### 4.2 Tushare Pro：建议拉取的接口清单（无分钟线版本）

按优先级：
- `trade_cal`：交易日历（用于补齐/对齐）
- `daily`：OHLC + `vol/amount`
- `adj_factor`：复权因子（用于 Qlib `factor`）
- `stk_limit`：涨跌停价（生成 `up_limit/down_limit`）
- `namechange`：名字变更（解析 ST/*ST → `is_st`）
- `suspend_d`：停复牌（标记停牌）
- `daily_basic`（强烈建议）：换手率/市值等（短线状态变量）

> 接口可用性会随账号权限变化；但从 Tushare Pro 文档来看，以下核心接口通常只要求 **≥2000 积分**（文档页可快速核对：  
> `trade_cal` doc_id=26；`daily` doc_id=27；`adj_factor` doc_id=28；`daily_basic` doc_id=32；`stk_limit` doc_id=183；`index_weight` doc_id=96）：  
> - `daily`（日线行情）  
> - `adj_factor`（复权因子）  
> - `daily_basic`（换手/市值等）  
> - `stk_limit`（逐股逐日涨跌停价）  
> - `trade_cal`（交易日历）  
> - `index_weight`（指数成分与权重，CSI500=000905.SH）  
> 你目前 10100 积分在“权限门槛”上应当足够，但仍建议你先运行：`scripts/tushare/probe_tushare_pro.py` 做最小调用自检（以你的 token 为准）。

### 4.2.1 建议基线数据：优先对齐 `examples/benchmarks_dynamic` 使用的数据
你提到希望后续训练以 “dynamic benchmark” 的数据为基线。仓库对应目录是 `examples/benchmarks_dynamic/`，其 README 推荐使用 **crowd-sourced 的 Qlib bin 数据**（包含 VWAP 等字段），并给出一键下载/解压到 `~/.qlib/qlib_data/cn_data` 的方式（示例）：

```bash
wget https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz
mkdir -p ~/.qlib/qlib_data/cn_data
tar -zxvf qlib_bin.tar.gz -C ~/.qlib/qlib_data/cn_data --strip-components=2
rm -f qlib_bin.tar.gz
```

使用该数据作为基线的价值：
- 与 `examples/benchmarks_dynamic/baseline/rolling_benchmark.py` 的实验设置一致，便于复现与横向对比
- 相比仓库内默认的 Yahoo 版本数据（`qlib/tests/data.py` 下载），该数据包含 VWAP（某些动态方法依赖）

`examples/benchmarks_dynamic/README.md` 给出的基线实验设定（供你对齐对比）：
- 数据集：Alpha158
- label horizon：20 个交易日
- rolling step：20 个交易日
- 测试 rolling 区间：2017-01 至 2020-08（按月滚动近似）

需要注意的局限：
- 该数据通常不包含 `up_limit/down_limit/is_st` 等“可交易性字段”。如果你要在短线波段研究中严格模拟涨跌停与 ST 过滤，建议在此基线数据之上，用 Tushare 增量补齐这些字段（或自建一份带这些字段的 Qlib 数据）。

### 4.2.2 已完成：CSI500 的 RR（Rolling Retrain）对齐验证（自建数据 vs crowd 基线）
为了确认你自建数据是否能“像微软那样”对齐 `examples/benchmarks_dynamic/` 的 RR 基线逻辑，我做了一次 **同配置、同市场口径** 的对比跑测，并把结果/配置/问题清单沉淀为可复现文档：
- 详细记录：`examples/benchmarks_dynamic/csi500_rr_compare/RR_BENCHMARK_COMPARISON.md`

**实验设定（用于 sanity check，而非你的最终 5D 策略）**
- horizon=20、step=20（对齐 `benchmarks_dynamic` RR baseline）
- TopkDropout（topk=50, n_drop=5），deal_price=close
- benchmark=SH000905，market=CSI500

**关键发现（解释“为什么你自建数据离 baseline 很远”）**
- 主要差异来自：你自建数据的 `csi500` instruments 属于 **静态/幸存者偏差口径**（测试期很多日期成分数 <500）。  
  这会显著抬高 Topk 策略回测收益，使其与 crowd baseline 不可比。

**修正方式（已落地）**
- 我把 crowd 的 **历史动态 CSI500 成分** 对齐到你的数据目录结构（仅证券代码大小写适配），并提供两种使用方式：
  1) **overlay provider（临时）**：在 `/tmp` 下把 `instruments/csi500.txt` 替换为动态成分，其余 `features/calendars` 仍用你的自建数据（适合快速验证、不污染原始数据）。  
  2) **落盘为新市场名（推荐长期用）**：在你的自建数据目录新增 `instruments/csi500_dyn.txt`，之后 workflow 里直接用 `market: csi500_dyn`（最省事、可复用）。

**修正后的结果（摘要）**
修正前后对比（horizon=20；step=20；含成本超额收益）：

| Model | Dataset | Ann. Ret (excess, with cost) | IR | Max DD |
|---|---|---:|---:|---:|
| RR[Linear] | crowd | 7.00% | 0.9697 | -17.57% |
| RR[Linear] | 自建（静态 csi500） | 24.81% | 3.1520 | -13.53% |
| RR[Linear] | 自建（动态 csi500_dyn） | 8.49% | 1.1644 | -16.70% |
| RR[LightGBM] | crowd | 9.18% | 1.2955 | -15.50% |
| RR[LightGBM] | 自建（静态 csi500） | 24.18% | 3.1271 | -10.54% |
| RR[LightGBM] | 自建（动态 csi500_dyn） | 13.32% | 1.9646 | -15.57% |

> 备注：我还额外做了一组 `step=120` 的 RR[DoubleEnsemble] 快速对比（避免 `step=20` 的小时级训练成本），同样是在“自建数据 + 动态成分”口径下得到 DoubleEnsemble 优于 LGBM 的趋势。  
> 具体指标、配置与 JSON 归档见：`examples/benchmarks_dynamic/csi500_rr_compare/RR_BENCHMARK_COMPARISON.md`。

**顺手定位出的一组“工程坑”（已在对比文档里列出规避方法）**
- handler cache 可能跨数据源复用导致“串数据”（hash 不包含 provider_uri）  
- crowd instruments 默认是 `SH/SZ`，你的 features 目录是 `sh/sz`（需要大小写适配）  
- Rolling 不会读取 YAML 里的 `qlib_init`（需要外部 `auto_init/qlib.init`）  
- 本仓库源码 Qlib 未编译扩展，直接在仓库目录运行会导入失败（建议在 `/tmp` 运行并导入已安装版 Qlib）

### 4.3 股票池：CSI500 动态成分（避免幸存者偏差）
必须使用“带日期范围”的动态成分，否则很容易引入幸存者偏差。推荐用 Qlib 自带脚本生成：
- `scripts/data_collector/cn_index/collector.py`（从 csindex 解析历史成分与变更）

> 补充：为了对齐 `benchmarks_dynamic` RR 基线，我已在你的自建 Qlib 数据目录新增了动态 CSI500 成分文件：  
> `/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin/instruments/csi500_dyn.txt`。后续所有“可比 benchmark / rolling”建议优先使用 `csi500_dyn`（见 4.2.2）。

### 4.4 ST 与停牌过滤策略（建议）

**ST：建议过滤（训练与回测一致）**
- 逻辑：ST 常伴随 5% 涨跌幅限制与较强事件风险，且易产生不可交易样本与极端厚尾
- 工程：用 `is_st` 字段在 instruments filter_pipe 中动态过滤

**停牌：不建议“先验过滤未来会停牌的股票”**
- 原因：实盘中你无法完美预知停牌；正确处理方式是在回测中体现“无法成交/被动持仓”
- 工程：用 `volume>0` 作为“当日可交易”的必要条件，但避免把它当作“未来可交易”的充分条件

---

## 5. 标签设计（Label Design：对齐平均持有≈5天）

### 5.1 决策时点与成交价对齐（无分钟线推荐方案）
推荐的研究闭环假设：
- 信号：T 日收盘后生成（用到 T 日日线信息）
- 成交：T+1 开盘成交（`deal_price: open`）

### 5.2 主标签：5 日 open-to-open（与平均持有期一致）
对每个交易日 T 定义标签：

```
LABEL_5D = Ref($open, -6) / Ref($open, -1) - 1
```

解释：
- `Ref($open, -1)` 是 T+1 开盘（买入价）
- `Ref($open, -6)` 是 T+6 开盘（卖出价），对应持有 5 个交易日

该定义的好处：
- 与回测 `deal_price=open` 同构（避免 label 与回测成交价不一致）
- 在无分钟线场景下，较容易解释与落地

### 5.3 稳健化：截面 rank 标签（推荐）
短线收益厚尾显著（涨跌停/事件）。建议把 label 做截面 rank 归一（例如 Qlib 的 `CSRankNorm`），让模型学“相对强弱”而不是点值，提升稳定性与抗异常值能力。

### 5.4 多标签扩展（后续实验）
建议同时评估多持有期标签，形成实验矩阵：
- `H ∈ {2, 5, 10}`（均为 open-to-open）
- 可做 ensemble：`score = w2*pred2 + w5*pred5 + w10*pred10`

---

## 6. 特征工程（Feature Engineering）

### 6.1 基线：Alpha158（先跑通再增强）
推荐第一阶段使用 Qlib `Alpha158` + 表格模型（LightGBM）建立强基线（强调闭环一致、结果可信）。

### 6.2 短线波段建议增强的“高价值特征族”
在不引入分钟线的前提下，优先补充以下信息（很多可由 `daily/daily_basic/stk_limit` 派生）：

1) **换手/流动性状态**：`turnover_rate`, `amount`, `float_mv`  
   - 用于检验 H3（状态依赖）与容量/冲击风险
2) **涨跌停接近度/触板风险**：  
   - `dist_up = (up_limit - price)/price`  
   - `dist_down = (price - down_limit)/price`  
3) **隔夜跳空/日内结构近似**（无分钟线）：  
   - `gap = open/Ref(close, 1) - 1`  
   - 振幅、短窗波动率等
4) **市场状态变量**（指数层）：  
   - 指数收益/波动/宽度（用于做 regime-aware 的信号稳定性评估）

### 6.3 信息泄露风险提示
短线策略的“高回测”常来自隐蔽泄露：
- 使用了未来才可知的成分股、ST 状态、财务数据发布时间
- 用当日收盘价生成信号却按当日收盘成交

工程上必须保证：
- instruments/过滤规则是“当日可得”的  
- label 与成交价与 shift 一致  
- 财务数据若使用，必须 PIT 化（否则直接放弃）

---

## 7. 模型与训练协议（Modeling & Training Protocol）

### 7.1 建议的基线模型
第一阶段建议：
- LightGBM（回归/排序均可）
- 标签：`LABEL_5D`（再叠加 `CSRankNorm`）

原因：短线研究最先需要的是“可解释、可复现、强基线”，不是复杂结构。

### 7.2 数据切分：walk-forward（必须）
短线非平稳性强，禁止只做一次固定切分后就下结论。建议：
- 以年/半年为步长滚动：训练窗口（如 5–8 年）→ 验证窗口（1–2 年）→ 测试窗口（1 年）
- 每个窗口都输出同样指标集合，并看“分年稳定性”

### 7.3 成本敏感性与稳健性检验（必须）
至少做三档成本压力测试：
- 成本 × 0.5 / × 1 / × 2

并统计：
- 交易次数、换手率、不可成交比例、持仓集中度
- 成本后超额收益的分年一致性

### 7.4 推荐基线 workflow：对齐 `examples/benchmarks_dynamic/` 的 Rolling 评估
如果你希望后续训练严格以 dynamic benchmark 为基线，建议直接复用其 **Rolling** 评估范式：
- 入口脚本：`examples/benchmarks_dynamic/baseline/rolling_benchmark.py`
- 核心实现：`qlib.contrib.rolling.base.Rolling`

Rolling 的价值在于把单次训练/测试拆成一系列“按时间滚动”的子任务，并把预测拼接后再统一评估，天然适配金融数据非平稳性。

需要注意的一点（影响 label）：当前 Rolling 会根据 `--horizon` 自动把 label 覆盖成 **close-to-close** 的多日收益（即 `Ref($close, -(horizon+1))/Ref($close, -1)-1`）。如果你未来坚持 open-to-open（更贴近 T+1 开盘成交），需要自定义 rolling 逻辑或避免自动覆盖。

示例（跑 rolling 的基本形态，参数按你实际研究周期调整）：

```bash
# 需要你已准备好 provider_uri（建议使用 benchmarks_dynamic 推荐的 crowd-sourced 数据）
python examples/benchmarks_dynamic/baseline/rolling_benchmark.py \
  --conf_path examples/benchmarks_dynamic/baseline/workflow_config_lightgbm_Alpha158.yaml \
  --horizon 5 \
  --step 20 \
  run
```

---

## 8. 组合构建与执行（Portfolio Construction）

### 8.1 用 Topk-Dropout 近似“平均持有≈5天”
若每天替换 `n_drop` 只、总持仓 `topk` 只，则平均持有期近似：

```
avg_hold ≈ topk / n_drop
```

注意：上述只是“**日频调仓**”下的近似；对应的双边换手率约为 `2 × n_drop / topk ≈ 2 / avg_hold`。当 `avg_hold≈5` 时，双边换手≈40%/日，**成本压力极大**。

结合我们在 `csi500_dyn` 上对 DoubleEnsemble Rolling 预测做的 TopkDropout 网格搜索（见 `hats_workflows/EXPERIMENT_LOG.md` 的 Phase 7.1.3），可以得到一个更准确的结论：
- 在 **topk>=20 的粗网格**里，高换手（>=40%）组合确实更容易被成本吞噬，成本后超额显著衰减
- 但在 **small-topk（更集中）+ n_drop=1** 的扩展搜索里，即便 turnover≈25%~40% 仍可能实现很高的成本后超额（代价是更高集中度与更敏感的回撤风险）

建议初值（与你的 20 万 + 100 股约束匹配）：
- 部署口径优先基线（当前窗口最优，见 Phase 7.1.3）：`topk=8`, `n_drop=1`（E[hold]≈8天，turnover≈25%/日；集中度更高，但在测试窗内回撤更可控）
- 更分散/更稳健备选：`topk=20`, `n_drop=2`（E[hold]≈10天，turnover≈20%/日；更容易满足 100 股下单约束）
- 若强约束“≈5天持有”：优先从 `topk=10,n_drop=2` 做压力测试；`topk=5,n_drop=1` 虽能满足持有≈5天，但扩展搜索显示回撤显著更大（见 Phase 7.1.3）

### 8.2 交易可达性设置（建议）
- `only_tradable: true`（只对当日可交易标的下单）
- 涨跌停限制：
  - **优先**：`limit_threshold: ("$open >= $up_limit", "$open <= $down_limit")`
  - **退而求其次**：常数阈值近似（如 0.095），但必须在报告中标注局限性

---

## 9. 评估指标与报告模板（Evaluation）

短线研究建议把指标分为三组：

### 9.1 信号层（不含组合构建）
- IC / RankIC、ICIR / RankICIR
- 分年/分市场状态的 IC 稳定性

### 9.2 组合层（含交易规则与成本）
- 成本后年化收益、信息比率（IR）、最大回撤（MDD）
- 换手率、交易次数、持仓集中度

### 9.3 可交易性与制度摩擦（短线必看）
- 不可成交比例（触板/停牌导致的未成交）
- 被动持仓天数（停牌/跌停卖不出）
- “胜率 vs 盈亏比”的分解（避免只看年化）

---

## 10. 实验矩阵（Ablation Matrix：建议的最小实验集）

建议从“最小但信息量最大”的消融开始。下表给出第一轮必做矩阵（可并行）：

| 维度 | 候选 | 目的 |
|---|---|---|
| 标签持有期 H | {2, 5, 10} | 检验 RQ1（哪个周期最稳） |
| 成交价 | {open} | 无分钟线优先保证一致性 |
| 限价规则 | {常数阈值, up/down limit} | 检验 RQ2（可交易性差异） |
| ST 过滤 | {off, on} | 检验 ST 对厚尾/不可成交影响 |
| topk | {20, 30, 40} | 容量/分散度与资金约束 |
| n_drop | {topk/4, topk/5, topk/6} | 换手—持有期权衡 |
| 成本倍率 | {0.5×, 1×, 2×} | 成本敏感性 |
| 风险过滤 | {off, on} | 检验 RQ4（稳定性） |

每个组合至少输出：
- RankIC（含分年）
- 成本后组合指标（含换手/不可成交统计）

---

## 11. 学术与业界研究综述（Related Work：中英混合视角）

本节给出“与你的短线波段直接相关”的研究方向与落地启示（不追求穷尽，但追求可用）。

### 11.1 日频动量、注意力与交易行为（短线信号来源）
- 部分研究在中国等新兴市场讨论日频层面的可预测性，并把其与投资者注意力/交易行为联系起来。  
  落地：把短窗动量与换手/成交额交互建模，做状态依赖检验（H3）。

### 11.2 涨跌停制度：磁吸/冷却/反转（可预测性与可交易性冲突的根源）
- 关于 magnet effect 与 cooling-off effect 的证据在不同样本、制度阶段与市场分组上可能存在差异。  
  落地：不要在回测里简化成常数阈值；用 `up_limit/down_limit`，并把“不可成交”作为研究指标，而不是当作噪声。

### 11.3 低波动/风险过滤（短线收益稳定器）
- 低风险/低波动在 A 股语境下经常被讨论，且往往伴随更低换手与更强可投资性。  
  落地：把风险过滤作为短线波段的二阶段排序/约束，提升成本后稳定性（H4）。

### 11.4 ML 资产定价与选股（方法论共识）
- 多篇综述/实证讨论 ML 在资产定价/选股的主要增益来自非线性与交互项，并强调严格样本外评估的重要性。  
  落地：优先把数据与回测约束做对，再谈深度模型；否则只是在拟合泄露与制度摩擦。

### 11.5 Qlib 生态（研究工程化）
- Qlib 提供端到端工作流：数据处理、特征/标签、训练、回测、报告。  
  落地：把“实验矩阵”固化为可复现 workflow（便于对比与回滚）。

> 建议检索锚点（便于你在 Scholar/SSRN/NBER/arXiv 快速定位）：  
> - Qlib：arXiv:2009.11189  
> - ML in asset pricing：Gu, Kelly, Xiu（RFS, 2020）  
> - 排序学习/关系建模：RSR（arXiv:1809.09441）、HIST（arXiv:2110.13716）  
> - DoubleEnsemble：arXiv:2010.01265（ICDM 2020）  
> - 日频动量（中国/新兴市场）：NBER w31839（Daily Momentum and New Investors in an Emerging Stock Market）  
> - 涨跌停制度与“可交易性偏差”：NBER w24014（Daily Price Limits and Destructive Market Behavior）  
> - 磁吸/冷却效应：arXiv:1803.09422（cooling-off）、Finance Research Letters 2023（price limit change & magnet effect）

---

## 12. 可复现交付物（Reproducibility Deliverables）

本仓库已提供（当你将来要实跑时可直接用）：
- 研究简版（要点）：`examples/csi500_swing5d/REPORT.md`
- 论文式研究报告（本文）：`examples/csi500_swing5d/RESEARCH_REPORT.md`
- 基线 workflow（可直接 qrun）：  
  - `examples/csi500_swing5d/workflow_config_lightgbm_alpha158_csi500_swing5d_open_base.yaml`  
  - `examples/csi500_swing5d/workflow_config_lightgbm_alpha158_csi500_swing5d_open_tushare.yaml`
- Tushare Pro 接口可用性自检：`scripts/tushare/probe_tushare_pro.py`

---

## 附录 A：Tushare → Qlib 字段映射建议（最小集合）

| 目标字段（Qlib） | 来源接口（Tushare） | 备注 |
|---|---|---|
| open/high/low/close | daily | 注意单位与缺失处理 |
| volume | daily.vol | 与 Qlib 字段命名统一（volume） |
| amount | daily.amount | 成交额，建议保留 |
| factor | adj_factor.adj_factor | 复权因子（用于 Qlib 的 factor 逻辑） |
| up_limit/down_limit | stk_limit | 逐股逐日涨跌停价 |
| is_st | namechange + 规则解析 | 需要用起止日期生成逐日标记 |
| suspended | suspend_d（可选） | 也可用 `volume==0`/缺失校验 |

---

## 附录 B：参数初值建议（面向 200,000 RMB）

| 模块 | 参数 | 建议初值 | 原因 |
|---|---:|---:|---|
| 组合 | topk | 30 | 分散 + 资金/100股约束平衡 |
| 组合 | n_drop | 6 | 平均持有≈5天（30/6） |
| 成交 | deal_price | open | 与无分钟线、T+1执行一致 |
| 交易 | trade_unit | 100 | A股常见最小单位 |
| 限价 | limit | up/down limit | 真实约束，替代常数阈值 |
| 标签 | horizon | 5D open-to-open | 与目标持有期一致 |

---

## 附录 C：中文文献与资料检索建议（覆盖“中文 + 英文”）

由于部分中文核心期刊/数据库存在访问门槛，建议你在 CNKI/万方/维普与高校图书馆资源中用以下关键词做定向检索，并优先选择“有制度改革/自然实验/高频或账户级数据”的研究：

**短线动量/反转（A股）**
- 关键词：`日内动量`、`短期反转`、`换手率`、`注意力`、`噪声交易`、`隔夜收益`、`波动率反馈`

**涨跌停制度**
- 关键词：`涨跌停 磁吸效应`、`涨跌停 冷却效应`、`涨停 反转`、`开板`、`触板 溢出效应`、`涨跌幅改革 自然实验`

**交易成本与可交易性**
- 关键词：`交易成本`、`冲击成本`、`容量约束`、`不可成交`、`停牌 风险`、`跌停 卖不出`

**机器学习选股**
- 关键词：`机器学习 选股`、`横截面排序 学习`、`图神经网络 行业 概念`、`非平稳`、`滚动训练 walk-forward`

---

## 参考文献（Selected References）

> 说明：本文是“研究设计报告”，因此参考文献以方法论与可复现框架为主；你后续做实证时可再补齐更细分的 A 股微观结构论文。

1. Yang, X. et al. **Qlib: An AI-oriented Quantitative Investment Platform**. arXiv:2009.11189.
2. Gu, S., Kelly, B., Xiu, D. **Empirical Asset Pricing via Machine Learning**. Review of Financial Studies, 2020.
3. Feng, F. et al. **Temporal Relational Ranking for Stock Prediction** (RSR). arXiv:1809.09441.
4. Xu, Y. et al. **HIST: Learning Hierarchical Stock Representation** (concept-based). arXiv:2110.13716.
5. Zhang, C. et al. **DoubleEnsemble: A New Ensemble Method Based on Sample Reweighting and Feature Selection for Financial Data Analysis**. arXiv:2010.01265.（ICDM 2020）
6. Gao, Z., Jiang, W., Xiong, W. A., Xiong, W. **Daily Momentum and New Investors in an Emerging Stock Market**. NBER Working Paper 31839, 2023. DOI: 10.3386/w31839.
7. Chen, T., Gao, Z., He, J., Jiang, W., Xiong, W. **Daily Price Limits and Destructive Market Behavior**. NBER Working Paper 24014, 2017. DOI: 10.3386/w24014.（发表于 Journal of Econometrics, 2018）
8. Wan, Y.-L. et al. **The cooling-off effect of price limits in the Chinese stock markets**. arXiv:1803.09422.（Physica A, 2018）
9. Zhang, X., Li, X., Hao, J., Li, P. **Price limit change and magnet effect: The role of investor attention**. Finance Research Letters, 2023. DOI: 10.1016/j.frl.2022.103577.
10. Qi, B. **Effectiveness of price limits: Evidence from China's ChiNext market**. PLoS ONE, 2023. DOI: 10.1371/journal.pone.0287548.
11. de Prado, M. L. **Advances in Financial Machine Learning**. Wiley, 2018.（用于 purged CV / embargo 等评估方法论）
