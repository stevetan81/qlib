# CSI500 Rolling Retrain (RR) Benchmark 对比（自建数据 vs crowd-sourced 标准数据）

本文档记录一次“对齐 `examples/benchmarks_dynamic/` 思路”的 **Rolling Retrain (RR)** 基准测试：  
- **同一套 RR 配置**（Alpha158 + Rolling/step=20/horizon=20 + TopkDropout）  
- **同一股票池**：`csi500`（基准 `SH000905`）  
- 分别在：
  - **自建 Qlib 数据**（你的导出数据）
  - **crowd-sourced Qlib 标准数据**（`investment_data` release 的 `qlib_bin.tar.gz`）
  上各跑一遍，比较结果差异。

> 备注：由于本仓库源码版 Qlib 未编译 C 扩展（`qlib.data._libs.rolling`），本次实验使用系统中已安装且可用的 Qlib（`/home/tanlu/qlib_src/qlib`）在 `/tmp` 下执行。  
> 这不影响配置与结果逻辑，但运行方式会与仓库内直接 `python examples/...` 略有不同。

---

## 1. 实验设置（对齐 benchmarks_dynamic RR）

**代码/版本**
- Python: 3.12.3
- Qlib: `0.9.8.dev18`
- LightGBM: `4.6.0`

**RR 关键参数**
- Rolling: `qlib.contrib.rolling.base.Rolling`
- `horizon=20`，`step=20`
- 训练/验证/测试（按交易日对齐后）：
  - 自建数据：train `2010-01-04 → 2014-12-31`（因日历从 2010 开始）  
  - crowd 数据：train `2008-01-02 → 2014-12-31`  
  - 两者 valid/test 一致：valid `2015-01-05 → 2016-12-30`；test `2017-01-03 → 2020-07-31`

**股票池/基准**
- 股票池：`csi500`
- 基准指数：`SH000905`

**策略与回测（与 benchmarks_dynamic baseline 一致）**
- Strategy：`TopkDropoutStrategy(topk=50, n_drop=5)`
- 成交价：`deal_price: close`
- 手续费：`open_cost=0.0005, close_cost=0.0015, min_cost=5`
- 初始资金：`account=100000000`（与 baseline 保持一致；更贴近论文 benchmark）

**配置文件（仓库内）**
- RR Linear:
  - `examples/benchmarks_dynamic/csi500_rr_compare/workflow_config_linear_Alpha158_csi500.yaml`（market=`csi500`）
  - `examples/benchmarks_dynamic/csi500_rr_compare/workflow_config_linear_Alpha158_csi500_dyn.yaml`（market=`csi500_dyn`）
- RR LightGBM:
  - `examples/benchmarks_dynamic/csi500_rr_compare/workflow_config_lightgbm_Alpha158_csi500.yaml`（market=`csi500`）
  - `examples/benchmarks_dynamic/csi500_rr_compare/workflow_config_lightgbm_Alpha158_csi500_dyn.yaml`（market=`csi500_dyn`）
- RR DoubleEnsemble:
  - `examples/benchmarks_dynamic/csi500_rr_compare/workflow_config_doubleensemble_Alpha158_csi500.yaml`（market=`csi500`）
  - `examples/benchmarks_dynamic/csi500_rr_compare/workflow_config_doubleensemble_Alpha158_csi500_dyn.yaml`（market=`csi500_dyn`）

**数据路径（本次实际运行使用）**
- 自建数据（原始）：`/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin`
- 自建数据（修正：dyn csi500 overlay）：`/tmp/qlib_own_dyn_csi500`（临时 overlay，用于本次快速验证）
- 自建数据（修正：落盘的动态股票池定义）：`/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin/instruments/csi500_dyn.txt`
- crowd 数据：`/tmp/qlib_crowd_cn_data`
  - 该目录由 `qlib_bin.tar.gz` 解压得到（本次解压用 `--strip-components=1`，因为 tarball 顶层是 `qlib_bin/`）

**实验产物**
- 统一的 mlflow 目录：`/tmp/rr_compare_csi500_20260207_212929/mlruns`
- 关键指标 JSON：`/tmp/rr_compare_csi500_20260207_212929/results/*.json`
  - 同时已把关键 JSON 归档进仓库：`examples/benchmarks_dynamic/csi500_rr_compare/run_outputs/`
  - 本次用到的归档目录：
    - `examples/benchmarks_dynamic/csi500_rr_compare/run_outputs/rr_compare_csi500_20260207_212929/`（自建原始 vs crowd，Linear/LGBM）
    - `examples/benchmarks_dynamic/csi500_rr_compare/run_outputs/rr_compare_csi500_own_dynpool_20260207_222822/`（自建+dyn成分，step=20，Linear/LGBM）
    - `examples/benchmarks_dynamic/csi500_rr_compare/run_outputs/rr_compare_csi500_own_dynpool_rr_step120_20260207_230805/`（自建+dyn成分，step=120，LGBM/DoubleEnsemble）

**重要注意（避免“串数据”）**
- RR 默认会把 `Alpha158` handler 缓存成 `Alpha158.<hash>.pkl`，位置在 **`conf_path` 同目录**。
- 该 `<hash>` 只由 handler 配置决定（不包含 `provider_uri`），所以如果你用**同一个** `conf_path` 先跑自建数据、再跑 crowd 数据，第二次可能会复用第一次生成的 handler cache，导致结果不可比。
- 本次对比通过把 YAML 复制到不同目录（`/tmp/.../runs/own_*` vs `.../runs/crowd_*`）来隔离 cache。

---

## 2. 结果汇总（与论文表格字段一致）

指标口径：
- Signal：`IC / ICIR / Rank IC / Rank ICIR`
- Portfolio：使用 `1day.excess_return_with_cost.*`（含成本、超额收益）

> 说明：`examples/benchmarks_dynamic/README.md` 里公开的基线表格是基于 `csi300`（见其 baseline 配置），本文为了贴合你的需求统一改为 `csi500`，因此**不应期待与 README 表格数值完全一致**；本文关注的是“同一市场口径下，自建数据 vs 标准数据”的可比性。

| Model | Dataset | IC | ICIR | Rank IC | Rank ICIR | Ann. Ret (excess, with cost) | IR | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| RR[Linear] | 自建数据 | 0.0894 | 0.7028 | 0.1086 | 0.8153 | 24.81% | 3.1520 | -13.53% |
| RR[Linear] | crowd 数据 | 0.0742 | 0.6764 | 0.0963 | 0.8707 | 7.00% | 0.9697 | -17.57% |
| RR[LightGBM] | 自建数据 | 0.0840 | 0.6723 | 0.0979 | 0.7590 | 24.18% | 3.1271 | -10.54% |
| RR[LightGBM] | crowd 数据 | 0.0806 | 0.7545 | 0.0989 | 0.9162 | 9.18% | 1.2955 | -15.50% |

> 上表的“自建数据”对应你原始的 `csi500` instruments（测试期很多日期 <500 只成分），因此它与 crowd-sourced 基线并不可比；下文第 4 节给出修正后的可比版本。

---

## 3. 关键差异点（为什么两份数据结果差很多）

### 3.1 `csi500` 股票池口径不一致（非常关键）
同样配置下，自建数据的组合收益显著高于 crowd 数据。首要原因通常是 **股票池是否存在“幸存者偏差/成分股口径偏差”**。

我对比了 `csi500` 在不同日期的“可用成分数”（按交易日过滤后的当日股票列表）：
- crowd 数据：测试区间内 **始终为 500**（符合 CSI500 定义）
- 自建数据：测试期明显少于 500（更像“当前成分股 + 上市日起算”的静态池）
  - 2017-01-03：329
  - 2018-01-02：364
  - 2019-01-02：381
  - 2020-07-31：411

这会导致两类问题：
- **幸存者偏差**：缺失“历史上曾经在 CSI500、但后来被剔除”的股票，回测结果会偏乐观。
- **池子规模变化**：模型选择空间变小/变大，会显著影响 Topk 策略收益与风险。

建议：如果要“像微软那样做可比 benchmark”，需要把自建数据的 `csi500` instruments 重建为 **历史动态成分**（可以用 Tushare `index_weight` 生成，或直接对齐 crowd 数据的 instruments 口径）。本次已经把动态成分**落盘**为 `csi500_dyn`（见第 4.1 节）。

### 3.2 训练起点不同（次要，但会影响）
自建数据日历从 2010 开始，导致 RR 的最早训练数据少了 2008-2009 两年；这会影响 early rolling 的模型稳定性与泛化。

---

## 4. 修正后：用“历史动态 CSI500 成分”跑自建数据（结果明显对齐）

为了验证“成分口径差异”是否是主因，我用 crowd 数据的 `csi500` 成分文件生成了一个 **自建数据的 overlay provider**：
- 目录：`/tmp/qlib_own_dyn_csi500`
- `calendars/`、`features/` 指向你的自建数据（软链接）
- `instruments/csi500.txt` 替换为 crowd 数据的动态成分（仅把证券代码改成小写 `sh/sz` 以匹配你的目录结构）

一个直观理解：**价格/因子数据完全还是你的**，我只把“今天应该属于 CSI500 的股票列表（带生效区间）”换成了动态口径，从而消除幸存者偏差与口径差异。

### 4.0 overlay provider 的生成方式（可复现）

本次实际做法等价于下面的流程（伪命令，路径按你的环境替换）：
```bash
# 1) 准备目标目录
rm -rf /tmp/qlib_own_dyn_csi500
mkdir -p /tmp/qlib_own_dyn_csi500

# 2) calendars/features 用自建数据（软链接，避免拷贝大文件）
ln -s /home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin/calendars /tmp/qlib_own_dyn_csi500/calendars
ln -s /home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin/features /tmp/qlib_own_dyn_csi500/features

# 3) instruments 先复制一份（很小），再替换 csi500.txt
cp -a /home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin/instruments /tmp/qlib_own_dyn_csi500/instruments
mv /tmp/qlib_own_dyn_csi500/instruments/csi500.txt /tmp/qlib_own_dyn_csi500/instruments/csi500.static.txt

# 4) 用 crowd 的动态成分覆盖；仅把证券代码从 SZ/SH 转成 sz/sh（匹配你的 features 目录）
python - <<'PY'
from pathlib import Path
src = Path('/tmp/qlib_crowd_cn_data/instruments/csi500.txt')
dst = Path('/tmp/qlib_own_dyn_csi500/instruments/csi500.txt')
out = []
for line in src.read_text(encoding='utf-8').splitlines():
    if not line.strip():
        continue
    sym, start, end = line.split('\\t')
    out.append(f\"{sym.lower()}\\t{start}\\t{end}\")
dst.write_text('\\n'.join(out) + '\\n', encoding='utf-8')
print('wrote', dst, 'lines', len(out))
PY
```

此时在测试期（2017-01-03 ~ 2020-07-31）任意一天，`csi500` 可用成分数都为 **500**，与 crowd 数据一致。

### 4.1 “落盘”版本（推荐后续长期使用）

为了让你后续不必再依赖 `/tmp` 的 overlay 目录，我已把动态成分写入你的自建数据目录中，作为一个新的市场名：
- 自建数据路径：`/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin`
- 新增文件：`instruments/csi500_dyn.txt`（动态成分，22000 行，带生效区间）

之后你只需要在任何 workflow YAML 中把 `market: csi500` 改成 `market: csi500_dyn`，即可在**同一份 features/calendars 数据**上使用动态 CSI500 成分进行训练/回测，从源头规避幸存者偏差。

### 4.1.1 你问的“两个选择”有什么不同？

两种方式的差别仅在**工程组织方式**，本质上都在解决同一个问题：让 CSI500 成分变成“带日期区间的动态口径”。

- **overlay provider（临时 /tmp）**
  - 做法：在 `/tmp` 下复用你的 `features/calendars`（软链接），只替换 `instruments/csi500.txt` 为动态成分。
  - 优点：快速验证、不修改原始数据；适合对齐 baseline/排查问题。
  - 缺点：目录在 `/tmp`，需要你管理好复现脚本与路径（重启/清理后需重建）。
- **落盘为 `csi500_dyn`（推荐长期用）**
  - 做法：把动态成分写入你的自建数据目录，作为 `instruments/csi500_dyn.txt`。
  - 优点：后续任何实验只需 `market: csi500_dyn`；复现成本最低、不依赖临时目录。
  - 缺点：需要对“动态成分来源”达成共识（本次对齐 crowd 口径；如果你想用 Tushare 或 csindex 生成，也可以替换该文件）。

### 4.2 修正后 RR 结果（自建数据）

| Model | Dataset | IC | ICIR | Rank IC | Rank ICIR | Ann. Ret (excess, with cost) | IR | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| RR[Linear] | 自建数据（dyn csi500） | 0.0728 | 0.6081 | 0.0980 | 0.8097 | 8.49% | 1.1644 | -16.70% |
| RR[LightGBM] | 自建数据（dyn csi500） | 0.0752 | 0.6558 | 0.0970 | 0.8477 | 13.32% | 1.9646 | -15.57% |

对比 crowd 数据（上表第 2 节）可以看到：
- RR[Linear] 已基本对齐（AnnRet 8.49% vs 7.00%，IC 0.0728 vs 0.0742）
- RR[LightGBM] 仍略偏强（13.32% vs 9.18%），但已不再是“离谱级别”的差距

本次修正后的指标 JSON 已归档：
- `examples/benchmarks_dynamic/csi500_rr_compare/run_outputs/rr_compare_csi500_own_dynpool_20260207_222822/RR_CSI500_Linear_OWN_DYNPOOL_20260207_222822.json`
- `examples/benchmarks_dynamic/csi500_rr_compare/run_outputs/rr_compare_csi500_own_dynpool_20260207_222822/RR_CSI500_LGBM_OWN_DYNPOOL_20260207_222822.json`

---

## 5. RR + DoubleEnsemble（可运行版本：step=120）

Rolling Retrain 里每一次滚动都会 **重新训练一次模型**。  
在本机上，`DEnsembleModel` 单次训练（非 rolling）约 10 分钟，因此若按 baseline 的 `step=20` 全量跑完 2017-2020，会非常耗时（小时级）。为保证“先能跑出结果并对比”，我先用 **`step=120`** 跑了一版 RR 对比（同样 `horizon=20`、同样 2017-2020 回测区间）。

| Model | step | IC | ICIR | Rank IC | Rank ICIR | Ann. Ret (excess, with cost) | IR | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| RR[LightGBM] | 120 | 0.0736 | 0.6407 | 0.0954 | 0.8316 | 12.11% | 1.7686 | -16.26% |
| RR[DoubleEnsemble] | 120 | 0.0810 | 0.6935 | 0.1024 | 0.8677 | 13.54% | 1.9988 | -12.09% |

从这组结果看：在你自建数据 + 动态成分口径下，DoubleEnsemble 在 `step=120` 的设定里同时提升了收益/IR，并显著改善了回撤。

本次 `step=120` 的指标 JSON 已归档：
- `examples/benchmarks_dynamic/csi500_rr_compare/run_outputs/rr_compare_csi500_own_dynpool_rr_step120_20260207_230805/RR_CSI500_LGBM_OWN_DYNPOOL_STEP120_20260207_230805.json`
- `examples/benchmarks_dynamic/csi500_rr_compare/run_outputs/rr_compare_csi500_own_dynpool_rr_step120_20260207_230805/RR_CSI500_DEnsemble_OWN_DYNPOOL_STEP120_20260207_230805.json`

---

## 6. 复现实验（最小可复现）

由于本仓库内源码 Qlib 未编译扩展，建议在 **仓库目录之外**（如 `/tmp`）运行，确保导入的是已安装的 Qlib。

示例（Linear + 自建数据）：
```bash
python - <<'PY'
from pathlib import Path
from qlib import auto_init
from qlib.config import REG_CN
from qlib.contrib.rolling.base import Rolling

root = Path('/tmp/rr_compare_csi500_20260207_212929')
conf_path = root / 'runs' / 'own_linear' / 'config.yaml'

auto_init(
  provider_uri='/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin',
  region=REG_CN,
  exp_manager={
    'class': 'MLflowExpManager',
    'module_path': 'qlib.workflow.expm',
    'kwargs': {'uri': f'file:{root}/mlruns', 'default_exp_name': 'Experiment'},
  },
)

Rolling(conf_path=conf_path, exp_name='RR_CSI500_Linear_OWN', horizon=20, step=20).run()
PY
```

---

## 7. 已分析的问题清单（以及如何规避）

1) **自建 `csi500` 成分口径问题（幸存者偏差/静态池）**  
   - 现象：测试期很多日期可用成分 <500（例如 2017-01-03 仅 329），导致回测显著偏乐观、与基线不可比。  
   - 处理：用“历史动态成分”替换 instruments（第 4 节 overlay provider），修正后 Linear RR 已基本与 crowd 数据对齐。

2) **跨数据源复用 handler cache 导致“串数据”**  
   - 原因：RR 会把 `Alpha158` handler 缓存成 `Alpha158.<hash>.pkl`（在 `conf_path` 同目录），而该 hash 不包含 `provider_uri`。  
   - 处理：不同数据源务必用不同目录的配置文件（或显式 `h_path`），避免第二次跑复用第一次的 handler cache。

3) **证券代码大小写不一致（crowd: `SH/SZ`，自建：`sh/sz`）**  
   - 影响：直接复用 crowd 的 instruments 会找不到你自建数据的 features 目录。  
   - 处理：overlay 时仅对 `csi500.txt` 的代码做 `.lower()`，日期区间不变（第 4.0 节）。

4) **Rolling 忽略 YAML 里的 `qlib_init` 段（必须外部 init）**  
   - 影响：如果你以为换 YAML 的 `provider_uri` 就能切数据源，实际 RR 仍可能用旧的 provider。  
   - 处理：在运行 RR 前用 `auto_init(provider_uri=..., exp_manager=...)`（或 `qlib.init(...)`）明确指定数据源。

5) **仓库源码版 Qlib 未编译扩展，直接在仓库目录运行会导入失败**  
   - 现象：`ModuleNotFoundError: qlib.data._libs.rolling`。  
   - 处理：在仓库目录之外（如 `/tmp`）运行，确保导入的是已安装/已编译的 Qlib。

6) **自建数据缺少 `day_future.txt` 会触发 warning**  
   - 现象：`TimeAdjuster(future=True)` 会提示“load calendar error… return current calendar”。  
   - 影响：对本次历史回测不致命，但容易造成误解；某些依赖 future calendar 的流程可能需要补齐。
