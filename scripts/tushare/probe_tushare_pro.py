#!/usr/bin/env python3
"""
Minimal probe for Tushare Pro interfaces needed by Qlib A-share short-term swing workflow.

Usage:
  export TUSHARE_TOKEN="..."
  python scripts/tushare/probe_tushare_pro.py

Notes:
  - This script will NOT print your token.
  - It only performs small queries (recent dates) to verify API availability/permissions.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from typing import Callable, Optional


def _print_kv(k: str, v: str) -> None:
    print(f"{k:<18} {v}")


def _safe_call(title: str, fn: Callable[[], object]) -> None:
    print(f"\n== {title} ==")
    try:
        out = fn()
        # Most tushare interfaces return pandas.DataFrame
        n_rows = getattr(out, "shape", (None, None))[0]
        cols = getattr(out, "columns", None)
        if n_rows is not None:
            _print_kv("rows:", str(n_rows))
        if cols is not None:
            _print_kv("columns:", ", ".join(list(cols)[:25]) + (" ..." if len(cols) > 25 else ""))
        if hasattr(out, "head"):
            print(out.head(3))
        else:
            print(out)
        _print_kv("status:", "OK")
    except Exception as e:  # noqa: BLE001 - probing tool
        _print_kv("status:", "FAIL")
        _print_kv("error:", repr(e))


def _yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _pick_latest_open_trade_date(pro, lookback_days: int = 30) -> Optional[str]:
    end = date.today()
    start = end - timedelta(days=lookback_days)
    df = pro.trade_cal(exchange="SSE", start_date=_yyyymmdd(start), end_date=_yyyymmdd(end))
    if df is None or df.empty:
        return None
    df = df[df["is_open"] == 1].sort_values("cal_date")
    if df.empty:
        return None
    return str(df.iloc[-1]["cal_date"])


def main() -> int:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("Missing env var: TUSHARE_TOKEN")
        print('Example: export TUSHARE_TOKEN="your_token_here"')
        return 2

    try:
        import tushare as ts  # type: ignore
    except Exception as e:  # noqa: BLE001
        print("Missing dependency: tushare")
        print("Install: pip install tushare")
        print(f"Import error: {e!r}")
        return 2

    ts.set_token(token)
    pro = ts.pro_api()

    print("Tushare Pro probe (token hidden)")
    _print_kv("today:", _yyyymmdd(date.today()))

    trade_date = None
    try:
        trade_date = _pick_latest_open_trade_date(pro, lookback_days=60)
    except Exception as e:  # noqa: BLE001
        _print_kv("trade_cal:", f"FAIL ({e!r})")

    _print_kv("probe_date:", trade_date or "N/A")

    if trade_date is None:
        print("\nCannot determine an open trading day via trade_cal; skip date-based probes.")
        return 1

    td = date(int(trade_date[:4]), int(trade_date[4:6]), int(trade_date[6:8]))
    start_30d = _yyyymmdd(td - timedelta(days=30))
    start_365d = _yyyymmdd(td - timedelta(days=365))

    # Core: daily OHLCV + amount
    _safe_call(
        "daily (OHLCV + amount)",
        lambda: pro.daily(trade_date=trade_date, fields="ts_code,trade_date,open,high,low,close,vol,amount"),
    )

    # Core: adjustment factor (for qlib 'factor')
    _safe_call(
        "adj_factor (复权因子)",
        lambda: pro.adj_factor(trade_date=trade_date, fields="ts_code,trade_date,adj_factor"),
    )

    # Strongly recommended: daily_basic (turnover/liquidity state)
    _safe_call(
        "daily_basic (换手/估值/市值等)",
        lambda: pro.daily_basic(trade_date=trade_date),
    )

    # Strongly recommended: per-stock daily price limits (10%/20%/ST 5% etc.)
    _safe_call(
        "stk_limit (涨跌停价)",
        lambda: pro.stk_limit(trade_date=trade_date),
    )

    # Optional: suspension info
    _safe_call(
        "suspend_d (停复牌)",
        lambda: pro.suspend_d(start_date=start_30d, end_date=trade_date),
    )

    # Optional: name change (parse ST/*ST periods)
    _safe_call(
        "namechange (名字变更/可解析 ST)",
        lambda: pro.namechange(start_date=start_365d, end_date=trade_date),
    )

    # Optional: CSI500 index weight (ts_code style: 000905.SH)
    _safe_call(
        "index_weight (CSI500, if permitted)",
        lambda: pro.index_weight(index_code="000905.SH", trade_date=trade_date),
    )

    print("\nNext steps (if you want to build Qlib dataset via tushare):")
    print("- Ensure you can fetch: daily + adj_factor (+ stk_limit, namechange, suspend_d, daily_basic)")
    print("- Dump into Qlib bin with fields: open/high/low/close/volume/factor (+ up_limit/down_limit/is_st/amount/...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
