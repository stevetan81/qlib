# 基于 Qlib 的 A 股（CSI500）短线波段研究与训练报告（平均持有≈5天）

> 目标：把“短线波段”的研究结论落地为一套 **可复现、可迭代、成本后可交易** 的 Qlib 训练/回测闭环。  
> 交易频率越高，**交易成本、涨跌停/停牌约束、数据质量** 对结果的影响越大；若不把这些约束内生化，回测高收益往往不可实现。

---

## 1. 你的设定与我们要解决的问题

你的输入：
- 平均持有期：约 5 天（小于 10 天）
- 股票池：CSI500（`csi500`），希望过滤 ST 与停牌（如果更好）
- 数据：有 Tushare Pro（10100 积分）；除分钟线外其他尽量可获取
- 初始资金：200,000 人民币（如不行则取系统允许最小值）

研究落地的关键挑战：
1) **短线收益分布厚尾**（涨跌停、事件驱动）→ label/损失函数/评估必须稳健  
2) **成交与制度约束强**（涨跌停、停牌、最小 100 股）→ 回测引擎参数必须匹配  
3) **非平稳性更强**（风格切换、制度变化、流动性周期）→ 需要 walk-forward/滚动训练  

---

## 2. 数据层：建议用 Tushare 自建一份“可交易”的 Qlib 数据

### 2.1 Qlib 日频数据的最低字段要求
Qlib 日频 backtest / handler 通常至少需要：
- `open/high/low/close/volume/factor`

并强烈建议额外准备（能显著提升短线可交易性建模）：
- `amount`（成交额，用于算 `vwap` 或流动性过滤）
- `up_limit/down_limit`（逐股逐日涨跌停价，用于精确 limit 规则）
- `is_st`（逐股逐日 ST 标记，用于过滤 ST）
- （可选）`turnover_rate/float_mv/total_mv` 等（来自 `daily_basic`，用于短线“换手/流动性状态”建模）

> 提醒：Qlib 的 `limit_threshold` 支持 **tuple 表达式**，你只要把 `up_limit/down_limit` dump 进数据，就能比“统一 9.5% 阈值”更贴近现实（尤其 ST 的 5% 与 20cm 个股）。

### 2.2 Tushare Pro（10100 积分）建议拉取的接口清单（按重要性）
用于“短线波段 + 可交易回测”的最小集合：
- `daily`：日线 OHLCV、`amount`
- `adj_factor`：复权因子（用于 `factor`）
- `stk_limit`：逐日涨跌停价（得到 `up_limit/down_limit`）
- `suspend_d`：停复牌（用于标记停牌日；也可用 `volume==0` 近似）
- `namechange`：名字变更（用于解析 ST/*ST 的起止区间）
- `trade_cal`：交易日历（对齐缺失日期与补全）
- （可选但强烈建议）`daily_basic`：换手率、估值、市值等，短线对“换手/流动性状态”很敏感

CSI500 成分获取有两条路：
- **推荐**：直接用 Qlib 自带的 `scripts/data_collector/cn_index/collector.py --index_name CSI500 --method parse_instruments` 抓取 csindex 历史变更，生成 `instruments/csi500.txt`（可复现且与 Qlib 生态一致）
- 备选：用 Tushare 的指数成分/权重接口（可能有权限/积分门槛差异）

你可以先用本仓库自检脚本确认接口是否可用：
- `scripts/tushare/probe_tushare_pro.py`

### 2.3 重要更新：CSI500 必须用“动态成分”（否则回测会虚高）
我们已对齐 `examples/benchmarks_dynamic/` 的 RR（Rolling Retrain）基线做过一次“自建数据 vs crowd 数据”的同配置对比，结论非常明确：
- 你自建数据里的 `csi500` 属于**静态/幸存者偏差口径**（测试期很多日期成分数 <500），会显著抬高 Topk 策略的回测收益，导致与你希望对齐的 baseline 不可比。
- 已落地修正：新增动态市场名 `csi500_dyn`（文件在 `/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin/instruments/csi500_dyn.txt`）。
  - 后续所有 rolling/benchmark 建议优先用 `market: csi500_dyn`。
- 详细结果、归档指标与问题清单：`examples/benchmarks_dynamic/csi500_rr_compare/RR_BENCHMARK_COMPARISON.md`

两种使用方式的区别（你之前问的“两个选择”）：
- **overlay provider（临时）**：在 `/tmp` 下用软链接复用你的 `features/calendars`，只替换 `instruments/csi500.txt` 为动态口径；优点是快速验证、不会修改原始数据。
- **落盘为 `csi500_dyn`（推荐长期用）**：直接在自建数据目录新增 `csi500_dyn.txt`；优点是后续所有 YAML 里改一个 `market` 就能复用，最省事。

---

## 3. 股票池与过滤：建议“过滤 ST”，停牌让交易所处理（更真实）

### 3.1 为什么建议过滤 ST
短线波段对“可交易性”与“风控稳定性”要求高：
- ST 常伴随基本面风险、公告冲击、5% 涨跌幅限制、流动性变差
- 训练集里 ST 样本会放大厚尾与不可成交样本，导致模型倾向于学习“回测里赚、现实里买不到/卖不出”的模式

因此建议：
- **训练/回测都过滤 ST**（风险管理上也合理）

### 3.2 停牌怎么处理更合理
停牌属于“真实会发生、且会影响持仓”的约束：
- 回测中应该允许你“被动持有、无法卖出”，这才接近现实
- 训练数据里停牌日通常是 NaN/0 成交量，`DropnaLabel` 会自动丢掉不可用样本

结论：
- 不建议用“过滤停牌=永远不持有会停牌的股票”这种强先验（现实很难做到）
- 但可以在 **下单层** 设置 `only_tradable: true`，并用 `limit_threshold` 规则限制不可交易日

---

## 4. 标签（Label）：把“平均持有≈5天”写进训练目标

你的策略是“平均持有约 5 天”，而非 1 天超短线。因此建议 label 与持有期一致：

### 4.1 更贴近可落地执行：T+1 开盘买入，持有 5 天后开盘卖出
- 交易时点：用 T 日收盘后信息产出信号 → T+1 开盘成交
- 5 天持有（open-to-open）label：

```
LABEL = Ref($open, -6) / Ref($open, -1) - 1
```

解释（对每个交易日 T）：
- `Ref($open, -1)`：T+1 的开盘价（买入）
- `Ref($open, -6)`：T+6 的开盘价（卖出）

> 这与 `TopkDropoutStrategy` 的“平均持有期≈topk/n_drop”近似一致。
>
> 注意：当 `avg_hold≈5` 且**日频调仓**时，双边换手约 `2×n_drop/topk≈40%/日`，对交易成本非常敏感；但是否“被成本吞噬”强烈依赖**集中度(topk)**。我们在动态池 `csi500_dyn` 的扩展搜索发现，small-topk + `n_drop=1` 在部署口径（`deal_price=open`, `account=200000`）下仍可实现很高的成本后超额（见 `hats_workflows/EXPERIMENT_LOG.md` 的 Phase 7.1.3）。

### 4.2 为短线厚尾做稳健化：用截面 Rank 标签
短线收益厚尾显著（涨跌停/事件），直接回归点值容易被极端样本支配。
建议对 label 做 **截面 Rank 归一化**（Qlib 内置 `CSRankNorm`），并以此训练回归模型做“相对强弱排序”。

---

## 5. 特征：先用 Alpha158 强基线，再逐步加“换手/流动性/涨跌停状态”

### 5.1 第一阶段（强基线）
用 Qlib 的 `Alpha158`（适配 LightGBM）跑通闭环：
- 先让流程稳定、指标可信（含成本/限制）
- 先追求稳定的 RankIC/成本后收益，再谈复杂模型

### 5.2 第二阶段（短线波段最该补的信号族）
强烈建议把 Tushare 的 `daily_basic` 与 `stk_limit` 信息落成字段/特征：
- 换手/流动性状态：`turnover_rate`、`amount`、`float_mv`（短线动量/反转常与换手状态耦合）
- “距涨跌停的空间”：`(up_limit - price)/price`、`(price - down_limit)/price`
- 波动与跳空：`(open/Ref(close,1)-1)`、短窗波动率/ATR（可用表达式或自定义字段）

---

## 6. 回测与执行假设：200,000 资金完全可用，但要注意 100 股约束

### 6.1 资金规模的现实影响
Qlib 回测会按 `trade_unit=100` 对买入股数做取整：
- 若 `topk` 太大，每只股票分到的资金太少，会出现“买不到（取整为 0）/现金闲置”导致回测失真

建议（已在 YAML 里体现）：
- 部署口径优先基线（当前窗口最优，见 Phase 7.1.3）：`topk: 8`、`n_drop: 1` → E[hold]≈8天（turnover≈25%/日），每只股票预算约 `200000/8≈25000`，更不易触发“买不到 100 股”
- 更分散/更稳健备选：`topk: 20`、`n_drop: 2` → E[hold]≈10天（turnover≈20%/日），每只股票预算约 `200000/20≈10000`
- 若强约束“≈5天持有”：可从 `topk: 5,n_drop: 1` 或 `topk: 10,n_drop: 2` 起步，但需特别关注回撤与不可成交统计（Phase 7.1.3 显示 `topk=5,n_drop=1` 回撤显著更大）

### 6.2 交易价（deal_price）的建议
在没有分钟线、又要避免前视偏差的情况下：
- 推荐 `deal_price: open`（更接近“前一日收盘后生成信号、次日开盘执行”）

### 6.3 涨跌停限制（强烈建议用逐日 up/down limit）
统一阈值（0.095）只能近似 10cm，而且无法覆盖：
- ST 5% / 创业板科创板 20% / 个别制度调整

若你能提供 `up_limit/down_limit` 字段：
- 用 `limit_threshold` 的 **tuple 表达式**模拟“触及涨跌停不可交易”（保守）：

```
limit_threshold:
  - "$open >= $up_limit"   # buy limit
  - "$open <= $down_limit" # sell limit
```

### 6.4 成本参数怎么设
短线对成本极其敏感，建议先用偏保守的成本：
- `open_cost`：双边佣金（按你的实际费率改）
- `close_cost`：佣金 +（可能的）印花税（卖出）等
- `min_cost`：常见为每笔 5 元（按券商改）
- `impact_cost`：用来模拟滑点/冲击成本（短线建议非零）

---

## 7. 训练与验证：必须做 walk-forward，并做“成本敏感性”压力测试

短线最容易“回测很好、样本外崩”：
- 风格与制度变化导致非平稳
- 成本轻微变化就能把利润抹掉

建议固定输出一份实验矩阵（最少做这些）：
1) 时间滚动：每年滚动训练/验证/测试（walk-forward）
2) 成本敏感：成本×0.5/×1/×2 三档
3) 组合超参：`topk`（20/30/40）、`n_drop`（topk/5 左右）、`only_tradable` 开关
4) 指标：成本后年化、回撤、换手、胜率、单次交易分布、分年表现

---

## 8. 学术研究（与你的短线波段最相关的“可落地点”）

你不需要把论文“照抄到因子里”，但要把其结论转成可检验假设：

### 8.1 日频动量/注意力
一些研究在中国等新兴市场发现 **日频动量**，并与注意力/交易行为联系起来。  
落地建议：
- 把短窗动量（1/2/3/5/10日）+ 量能/换手（attention/liquidity proxy）作为核心特征族
- 采用截面 rank 目标降低厚尾干扰

### 8.2 涨跌停制度带来的“可预测性 vs 可交易性”
涨跌停会制造统计异常（磁吸/延迟价格发现/过度反应/次日反转等），但也会让“可套利空间”被成交约束吞噬。  
落地建议：
- 回测必须内生化涨跌停限制（逐日 up/down limit）
- 特征加入“距涨跌停空间/近期触板次数”等状态变量

### 8.3 低波动/风险过滤
低波动效应在 A 股被多篇研究讨论；对短线波段而言，风险过滤往往能显著改善成本后曲线稳定性。  
落地建议：
- 在选股排序里加入波动惩罚（两阶段：先预测收益，再按波动/回撤过滤或多目标排序）

### 8.4 ML 选股研究的共识（与 Qlib 工作流一致）
不少资产定价/选股文献表明：ML 的收益常来自非线性交互与更好的泛化控制；  
在工程上，最可靠路径通常是：
- 先用强基线（LGB + Alpha158）把闭环跑稳定
- 再加入更贴近市场结构的信息（概念/行业图、MoE、对抗训练等）

---

## 9. 你现在就能执行的最短路径（建议按顺序做）
1) 运行 `scripts/tushare/probe_tushare_pro.py` 自检接口可用性
2) 用 `scripts/data_collector/cn_index/collector.py` 生成 CSI500 instruments
3) 先跑 `workflow_config_lightgbm_alpha158_csi500_swing5d_open_base.yaml`（确认流程跑通、指标可信）
4) 用 Tushare 自建数据补齐 `up_limit/down_limit/is_st` 后，再跑 `*_tushare.yaml`（提升可交易性与现实一致性）
5) 开始 walk-forward + 成本敏感性矩阵，选出稳定配置再做特征/模型迭代

---

## 参考文献与方向索引（便于你后续深入）
（下面给出“检索锚点”：NBER 编号 / arXiv / 会议论文名；你可以用这些在学术搜索中快速定位原文）

```text
Qlib: arXiv:2009.11189  (Qlib: an AI-oriented Quantitative Investment Platform)
ML in asset pricing: Gu, Kelly, Xiu (Review of Financial Studies, 2020)
Temporal Relational Ranking (RSR): arXiv:1809.09441
HIST (concept-based): arXiv:2110.13716
Adv-ALSTM (adversarial): IJCAI 2019 paper "Adversarial Attentive LSTM for Stock Price Manipulation Detection/Prediction" (相关方向)
Daily momentum / investor attention (China/emerging mkts): NBER Working Paper w31839
Price limits & reversal / trading constraint effects: NBER Working Paper w24014
创业板 10%→20% 涨跌幅改革与磁吸/价格发现：可检索 "ChiNext price limit reform magnet effect"
Low volatility anomaly in China A-shares: 可检索 "low volatility effect China A-shares"
```
