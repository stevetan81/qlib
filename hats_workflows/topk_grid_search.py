#!/usr/bin/env python3
"""TopkDropout 策略参数网格搜索

基于 DoubleEnsemble Rolling (h=5, s=20) 的预测结果，
测试不同 topk/n_drop 组合。

用法:
    # 建议在 /tmp 目录运行，避免导入到仓库内未编译的 qlib 源码
    cd /tmp

    # 指定 pred.pkl（推荐：rolling_benchmark.py 生成的 merged pred.pkl）
    python /home/tanlu/myworkspace/qlib/hats_workflows/topk_grid_search.py \\
      --pred_path /path/to/pred.pkl

    # 自定义 topk/n_drop 搜索空间
    python /home/tanlu/myworkspace/qlib/hats_workflows/topk_grid_search.py \\
      --pred_path /path/to/pred.pkl \\
      --topk_list 20,30,50,80 \\
      --n_drop_list 2,3,5,10,15
"""
from __future__ import annotations

import argparse
from pathlib import Path

import qlib
from qlib.config import REG_CN
from qlib.contrib.evaluate import backtest_daily, risk_analysis
from qlib.utils.pickle_utils import restricted_pickle_load

PROVIDER_URI = "/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin"

TOPK_LIST = [20, 30, 50, 80]
N_DROP_LIST = [2, 3, 5, 10, 15]

BACKTEST_CONFIG = dict(
    start_time="2025-01-01",
    end_time="2026-01-30",
    account=100000000,
    benchmark="SH000905",
    exchange_kwargs=dict(
        limit_threshold=0.095,
        deal_price="close",
        open_cost=0.0005,
        close_cost=0.0015,
        min_cost=5,
    ),
)


def _parse_int_list(text: str) -> list[int]:
    values: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        values.append(int(part))
    return values


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TopkDropout 网格搜索（基于 pred.pkl 回测）")
    parser.add_argument("--provider_uri", default=PROVIDER_URI, help="Qlib provider_uri（默认 HATS qlib_bin）")
    parser.add_argument("--pred_path", required=True, help="Rolling 预测结果 pred.pkl 路径")
    parser.add_argument("--start_time", default=BACKTEST_CONFIG["start_time"])
    parser.add_argument("--end_time", default=BACKTEST_CONFIG["end_time"])
    parser.add_argument("--account", type=float, default=BACKTEST_CONFIG["account"])
    parser.add_argument("--benchmark", default=BACKTEST_CONFIG["benchmark"])

    exchange_kwargs = BACKTEST_CONFIG["exchange_kwargs"]
    parser.add_argument("--limit_threshold", type=float, default=exchange_kwargs["limit_threshold"])
    parser.add_argument("--deal_price", default=exchange_kwargs["deal_price"])
    parser.add_argument("--open_cost", type=float, default=exchange_kwargs["open_cost"])
    parser.add_argument("--close_cost", type=float, default=exchange_kwargs["close_cost"])
    parser.add_argument("--min_cost", type=float, default=exchange_kwargs["min_cost"])

    parser.add_argument("--topk_list", default=",".join(map(str, TOPK_LIST)), help="逗号分隔，如 20,30,50")
    parser.add_argument("--n_drop_list", default=",".join(map(str, N_DROP_LIST)), help="逗号分隔，如 2,3,5")
    parser.add_argument("--only_tradable", action="store_true", help="TopkDropoutStrategy.only_tradable=true")
    parser.add_argument(
        "--allow_trade_at_limit",
        action="store_true",
        help="更贴近实盘：允许在涨停卖出/跌停买入（forbid_all_trade_at_limit=false）",
    )
    parser.add_argument("--output_csv", default="", help="可选：保存结果到 CSV")
    return parser


def _markdown_table(rows: list[dict], headers: list[str]) -> str:
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * (len(headers) + 0)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def main():
    args = _build_arg_parser().parse_args()

    pred_path = Path(args.pred_path).expanduser()
    if not pred_path.exists():
        raise FileNotFoundError(f"pred.pkl not found: {pred_path}")

    qlib.init(provider_uri=args.provider_uri, region=REG_CN)

    # Load prediction
    with open(pred_path, "rb") as f:
        pred = restricted_pickle_load(f)
    print(f"Loaded prediction: {pred.shape}")

    topk_list = _parse_int_list(args.topk_list)
    n_drop_list = _parse_int_list(args.n_drop_list)

    backtest_config = dict(
        start_time=args.start_time,
        end_time=args.end_time,
        account=args.account,
        benchmark=args.benchmark,
        exchange_kwargs=dict(
            limit_threshold=args.limit_threshold,
            deal_price=args.deal_price,
            open_cost=args.open_cost,
            close_cost=args.close_cost,
            min_cost=args.min_cost,
        ),
    )

    results = []
    for topk in topk_list:
        for n_drop in n_drop_list:
            if n_drop >= topk / 2:
                continue
            turnover = 2 * n_drop / topk  # buy+sell turnover per rebalance
            expected_holding = topk / n_drop  # expected holding days (rough)
            print(
                f"\ntopk={topk}, n_drop={n_drop}, turnover={turnover:.0%}, E[hold]≈{expected_holding:.1f}d ... ",
                end="",
                flush=True,
            )
            try:
                strategy_config = {
                    "class": "TopkDropoutStrategy",
                    "module_path": "qlib.contrib.strategy",
                    "kwargs": {
                        "signal": pred,
                        "topk": topk,
                        "n_drop": n_drop,
                        "only_tradable": args.only_tradable,
                        "forbid_all_trade_at_limit": (not args.allow_trade_at_limit),
                    },
                }
                report_normal, positions = backtest_daily(strategy=strategy_config, **backtest_config)

                # risk_analysis returns a DataFrame with rows:
                #   [mean, std, annualized_return, information_ratio, max_drawdown]
                # Each cell is a pd.Series with keys: [return, bench, cost, ...]
                analysis = risk_analysis(report_normal)

                # NOTE:
                # - report_normal["return"] is *without* transaction cost
                # - report_normal["cost"] is a positive cost ratio
                # So: return_with_cost = return - cost
                ann_ret_wo_cost = analysis.loc["annualized_return", "risk"]["return"]
                ann_bench = analysis.loc["annualized_return", "risk"]["bench"]
                ann_cost = analysis.loc["annualized_return", "risk"]["cost"]
                ann_ret_w_cost = ann_ret_wo_cost - ann_cost

                excess_wo_cost = report_normal["return"] - report_normal["bench"]
                excess_w_cost = report_normal["return"] - report_normal["cost"] - report_normal["bench"]

                excess_wo_cost_ra = risk_analysis(excess_wo_cost)
                excess_w_cost_ra = risk_analysis(excess_w_cost)

                excess_w_cost_ann = float(excess_w_cost_ra.loc["annualized_return", "risk"])
                excess_wo_cost_ann = float(excess_wo_cost_ra.loc["annualized_return", "risk"])
                ir = float(excess_w_cost_ra.loc["information_ratio", "risk"])
                max_dd = float(excess_w_cost_ra.loc["max_drawdown", "risk"])

                results.append({
                    "topk": topk,
                    "n_drop": n_drop,
                    "turnover": f"{turnover:.0%}",
                    "E_hold_days": f"{expected_holding:.1f}",
                    "ann_return": f"{ann_ret_w_cost:.1%}",
                    "ann_bench": f"{ann_bench:.1%}",
                    "excess_w_cost": f"{excess_w_cost_ann:.1%}",
                    "excess_no_cost": f"{excess_wo_cost_ann:.1%}",
                    "IR": f"{ir:.2f}",
                    "MaxDD": f"{max_dd:.1%}",
                })
                print(f"excess(w_cost)={excess_w_cost_ann:.1%}, IR={ir:.2f}, MaxDD={max_dd:.1%}")
            except Exception as e:
                import traceback
                print(f"ERROR: {e}")
                traceback.print_exc()

    # Print results table
    if results:
        import pandas as pd
        df = pd.DataFrame(results)
        print("\n" + "=" * 90)
        print("TopkDropout Grid Search Results")
        print("=" * 90)
        print(df.to_string(index=False))
        print("\nMarkdown table (copy/paste):")
        headers = ["topk", "n_drop", "turnover", "E_hold_days", "ann_return", "ann_bench", "excess_w_cost", "excess_no_cost", "IR", "MaxDD"]
        print(_markdown_table(results, headers))
        print("=" * 90)

        if args.output_csv:
            out_path = Path(args.output_csv).expanduser()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(out_path, index=False)
            print(f"Saved CSV: {out_path}")


if __name__ == "__main__":
    main()
