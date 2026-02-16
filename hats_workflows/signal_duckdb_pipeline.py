#!/usr/bin/env python3
"""Qlib daily signal pipeline with DuckDB persistence and live reconciliation."""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import duckdb
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("signal_duckdb_pipeline")

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(name: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid SQL identifier: {name}")
    return name


def parse_any_date(value: object) -> date:
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="raise")
    return parsed.date()


def normalize_instrument(value: object) -> str:
    text = str(value).strip().upper()
    if not text:
        raise ValueError("instrument is empty")

    text = text.replace(" ", "")
    if "." in text:
        code, suffix = text.split(".", 1)
        suffix = suffix.upper()
        if suffix in {"SH", "XSHG"}:
            return f"SH{code.zfill(6)}"
        if suffix in {"SZ", "XSHE"}:
            return f"SZ{code.zfill(6)}"
        raise ValueError(f"unsupported instrument suffix: {suffix}")

    if text.startswith(("SH", "SZ")):
        return f"{text[:2]}{text[2:].zfill(6)}"

    digits = "".join(character for character in text if character.isdigit())
    if len(digits) == 6:
        market = "SH" if digits[0] in {"5", "6", "9"} else "SZ"
        return f"{market}{digits}"

    raise ValueError(f"cannot normalize instrument: {value}")


def instrument_to_tscode(instrument: str) -> str:
    normalized = normalize_instrument(instrument)
    return f"{normalized[2:]}.{normalized[:2]}"


def tscode_to_instrument(ts_code: object) -> str:
    return normalize_instrument(ts_code)


def table_exists(connection: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    query = """
    SELECT COUNT(*) AS count
    FROM information_schema.tables
    WHERE table_schema = 'main' AND table_name = ?
    """
    result = connection.execute(query, [table_name]).fetchone()
    return bool(result and result[0] > 0)


def get_existing_columns(connection: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    if not table_exists(connection, table_name):
        return set()
    rows = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return {row[1] for row in rows}


def ensure_prediction_table(connection: duckdb.DuckDBPyConnection, table_name: str) -> None:
    table_name = validate_identifier(table_name)
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            signal_date DATE NOT NULL,
            trade_date DATE,
            instrument VARCHAR NOT NULL,
            score DOUBLE,
            rank INTEGER,
            is_selected BOOLEAN,
            model_name VARCHAR NOT NULL,
            topk INTEGER,
            n_drop INTEGER,
            source_file VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (signal_date, instrument, model_name)
        )
        """
    )


def ensure_orders_table(connection: duckdb.DuckDBPyConnection, table_name: str) -> None:
    table_name = validate_identifier(table_name)
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            signal_date DATE NOT NULL,
            trade_date DATE NOT NULL,
            instrument VARCHAR NOT NULL,
            side VARCHAR NOT NULL,
            score DOUBLE,
            rank INTEGER,
            model_name VARCHAR NOT NULL,
            topk INTEGER,
            n_drop INTEGER,
            source VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (signal_date, instrument, side, model_name)
        )
        """
    )


def ensure_executions_table(connection: duckdb.DuckDBPyConnection, table_name: str) -> None:
    table_name = validate_identifier(table_name)
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            trade_date DATE NOT NULL,
            instrument VARCHAR NOT NULL,
            side VARCHAR NOT NULL,
            filled_qty DOUBLE,
            avg_price DOUBLE,
            status VARCHAR,
            order_id VARCHAR NOT NULL,
            broker_name VARCHAR,
            source_file VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, instrument, side, order_id)
        )
        """
    )


def ensure_reconcile_table(connection: duckdb.DuckDBPyConnection, table_name: str) -> None:
    table_name = validate_identifier(table_name)
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            trade_date DATE NOT NULL,
            instrument VARCHAR NOT NULL,
            side VARCHAR NOT NULL,
            model_name VARCHAR NOT NULL,
            signal_date DATE,
            score DOUBLE,
            rank INTEGER,
            executed BOOLEAN,
            filled_qty DOUBLE,
            avg_price DOUBLE,
            reference_open DOUBLE,
            slippage_bps DOUBLE,
            status VARCHAR,
            note VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, instrument, side, model_name)
        )
        """
    )


def add_missing_columns(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    column_types: dict[str, str],
) -> None:
    existing = get_existing_columns(connection, table_name)
    for column_name, column_type in column_types.items():
        if column_name not in existing:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def upsert_dataframe(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    dataframe: pd.DataFrame,
    key_columns: list[str],
) -> int:
    if dataframe.empty:
        return 0

    table_name = validate_identifier(table_name)
    table_columns = [
        row[1]
        for row in connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    ]
    insert_columns = [column for column in table_columns if column in dataframe.columns]
    if not insert_columns:
        raise ValueError(f"No matching columns for table {table_name}")

    payload = dataframe[insert_columns].copy()
    temp_view = "upsert_payload"
    connection.register(temp_view, payload)

    column_clause = ", ".join(insert_columns)
    update_columns = [column for column in insert_columns if column not in key_columns]
    if update_columns:
        update_clause = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
        sql = (
            f"INSERT INTO {table_name} ({column_clause}) "
            f"SELECT {column_clause} FROM {temp_view} "
            f"ON CONFLICT ({', '.join(key_columns)}) DO UPDATE SET {update_clause}"
        )
    else:
        sql = (
            f"INSERT INTO {table_name} ({column_clause}) "
            f"SELECT {column_clause} FROM {temp_view} "
            f"ON CONFLICT ({', '.join(key_columns)}) DO NOTHING"
        )

    connection.execute(sql)
    connection.unregister(temp_view)
    return len(payload)


def normalize_side(value: object) -> str:
    text = str(value).strip().upper()
    buy_aliases = {"B", "BUY", "LONG", "OPEN_LONG", "买入"}
    sell_aliases = {"S", "SELL", "SHORT", "CLOSE_LONG", "卖出"}
    if text in buy_aliases:
        return "BUY"
    if text in sell_aliases:
        return "SELL"
    return text


def find_first_column(frame: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    lookup = {column.lower(): column for column in frame.columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    return None


def infer_signal_date(frame: pd.DataFrame, explicit_signal_date: Optional[str]) -> date:
    if explicit_signal_date:
        return parse_any_date(explicit_signal_date)

    date_column = find_first_column(frame, ["signal_date", "datetime", "date", "trade_date"])
    if not date_column:
        raise ValueError("Cannot infer signal date. Pass --signal-date explicitly.")

    date_values = pd.to_datetime(frame[date_column], errors="coerce").dropna().dt.date.unique()
    if len(date_values) == 0:
        raise ValueError("Cannot infer valid signal date from prediction file.")
    if len(date_values) > 1:
        selected_date = max(date_values)
        logger.warning(
            "Prediction file contains %d dates; using latest %s. "
            "Pass --signal-date to override.",
            len(date_values),
            selected_date.isoformat(),
        )
        return selected_date
    return date_values[0]


def get_next_trade_date(connection: duckdb.DuckDBPyConnection, signal_date: date) -> date:
    if table_exists(connection, "daily"):
        row = connection.execute(
            "SELECT MIN(trade_date) FROM daily WHERE trade_date > ?",
            [signal_date],
        ).fetchone()
        if row and row[0]:
            return parse_any_date(row[0])
    return signal_date + timedelta(days=1)


def load_prediction_dataframe(
    pred_csv: Path,
    signal_date: date,
    trade_date: date,
    model_name: str,
    topk: int,
    n_drop: int,
) -> pd.DataFrame:
    source_frame = pd.read_csv(pred_csv)
    date_column = find_first_column(source_frame, ["signal_date", "datetime", "date", "trade_date"])
    instrument_column = find_first_column(source_frame, ["instrument", "ts_code", "ticker", "symbol"])
    score_column = find_first_column(source_frame, ["score", "pred_score", "prediction", "qlib_score"])
    rank_column = find_first_column(source_frame, ["rank", "pred_rank"])

    if not instrument_column or not score_column:
        raise ValueError("Prediction CSV must contain instrument and score columns.")

    if date_column:
        parsed_dates = pd.to_datetime(source_frame[date_column], errors="coerce").dt.date
        source_frame = source_frame[parsed_dates == signal_date]
        if source_frame.empty:
            raise ValueError(f"No prediction rows found for signal date {signal_date}.")

    frame = source_frame[[instrument_column, score_column] + ([rank_column] if rank_column else [])].copy()
    frame = frame.rename(
        columns={
            instrument_column: "instrument",
            score_column: "score",
            **({rank_column: "rank"} if rank_column else {}),
        }
    )

    frame["instrument"] = frame["instrument"].map(normalize_instrument)
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    frame = frame.dropna(subset=["instrument", "score"]).drop_duplicates(subset=["instrument"])
    frame = frame.sort_values("score", ascending=False).reset_index(drop=True)

    frame["rank"] = range(1, len(frame) + 1)

    frame["signal_date"] = signal_date
    frame["trade_date"] = trade_date
    frame["model_name"] = model_name
    frame["topk"] = int(topk)
    frame["n_drop"] = int(n_drop)
    frame["is_selected"] = frame["rank"] <= int(topk)
    frame["source_file"] = str(pred_csv.resolve())
    frame["created_at"] = datetime.now()
    return frame


def get_previous_selected(
    connection: duckdb.DuckDBPyConnection,
    prediction_table: str,
    model_name: str,
    signal_date: date,
) -> tuple[Optional[date], pd.DataFrame]:
    prediction_table = validate_identifier(prediction_table)
    previous_row = connection.execute(
        f"""
        SELECT MAX(signal_date)
        FROM {prediction_table}
        WHERE model_name = ? AND signal_date < ?
        """,
        [model_name, signal_date],
    ).fetchone()

    previous_date = parse_any_date(previous_row[0]) if previous_row and previous_row[0] else None
    if previous_date is None:
        return None, pd.DataFrame(columns=["instrument", "score", "rank"])

    previous_frame = connection.execute(
        f"""
        SELECT instrument, score, rank
        FROM {prediction_table}
        WHERE model_name = ? AND signal_date = ? AND COALESCE(is_selected, FALSE) = TRUE
        """,
        [model_name, previous_date],
    ).fetchdf()
    if previous_frame.empty:
        return previous_date, pd.DataFrame(columns=["instrument", "score", "rank"])
    previous_frame["instrument"] = previous_frame["instrument"].map(normalize_instrument)
    return previous_date, previous_frame


def build_orders(
    current_prediction: pd.DataFrame,
    previous_selected: pd.DataFrame,
    signal_date: date,
    trade_date: date,
    model_name: str,
    topk: int,
    n_drop: int,
    include_hold: bool,
) -> pd.DataFrame:
    current_selected = current_prediction[current_prediction["is_selected"]].copy()
    current_map = current_selected.set_index("instrument")[["score", "rank"]]
    previous_map = (
        previous_selected.set_index("instrument")[["score", "rank"]]
        if not previous_selected.empty
        else pd.DataFrame(columns=["score", "rank"])
    )

    current_set = set(current_map.index)
    previous_set = set(previous_map.index)
    buy_set = current_set - previous_set
    sell_set = previous_set - current_set
    hold_set = current_set & previous_set

    rows: list[dict[str, object]] = []
    timestamp = datetime.now()
    for instrument in sorted(buy_set):
        rows.append(
            {
                "signal_date": signal_date,
                "trade_date": trade_date,
                "instrument": instrument,
                "side": "BUY",
                "score": float(current_map.loc[instrument, "score"]),
                "rank": int(current_map.loc[instrument, "rank"]),
                "model_name": model_name,
                "topk": topk,
                "n_drop": n_drop,
                "source": "prediction",
                "created_at": timestamp,
            }
        )

    for instrument in sorted(sell_set):
        score = previous_map.loc[instrument, "score"] if instrument in previous_map.index else None
        rank = previous_map.loc[instrument, "rank"] if instrument in previous_map.index else None
        rows.append(
            {
                "signal_date": signal_date,
                "trade_date": trade_date,
                "instrument": instrument,
                "side": "SELL",
                "score": float(score) if pd.notna(score) else None,
                "rank": int(rank) if pd.notna(rank) else None,
                "model_name": model_name,
                "topk": topk,
                "n_drop": n_drop,
                "source": "prediction",
                "created_at": timestamp,
            }
        )

    if include_hold:
        for instrument in sorted(hold_set):
            rows.append(
                {
                    "signal_date": signal_date,
                    "trade_date": trade_date,
                    "instrument": instrument,
                    "side": "HOLD",
                    "score": float(current_map.loc[instrument, "score"]),
                    "rank": int(current_map.loc[instrument, "rank"]),
                    "model_name": model_name,
                    "topk": topk,
                    "n_drop": n_drop,
                    "source": "prediction",
                    "created_at": timestamp,
                }
            )

    if not rows:
        return pd.DataFrame(
            columns=[
                "signal_date",
                "trade_date",
                "instrument",
                "side",
                "score",
                "rank",
                "model_name",
                "topk",
                "n_drop",
                "source",
                "created_at",
            ]
        )
    return pd.DataFrame(rows)


def run_ingest_prediction(arguments: argparse.Namespace) -> None:
    pred_csv = Path(arguments.pred_csv).expanduser().resolve()
    if not pred_csv.exists():
        raise FileNotFoundError(f"Prediction CSV not found: {pred_csv}")

    with duckdb.connect(arguments.db_path) as connection:
        ensure_prediction_table(connection, arguments.prediction_table)
        ensure_orders_table(connection, arguments.orders_table)
        add_missing_columns(
            connection,
            arguments.prediction_table,
            {
                "trade_date": "DATE",
                "is_selected": "BOOLEAN",
                "topk": "INTEGER",
                "n_drop": "INTEGER",
                "source_file": "VARCHAR",
                "created_at": "TIMESTAMP",
            },
        )
        add_missing_columns(
            connection,
            arguments.orders_table,
            {
                "score": "DOUBLE",
                "rank": "INTEGER",
                "topk": "INTEGER",
                "n_drop": "INTEGER",
                "source": "VARCHAR",
                "created_at": "TIMESTAMP",
            },
        )

        source_frame = pd.read_csv(pred_csv)
        signal_date = infer_signal_date(source_frame, arguments.signal_date)
        trade_date = (
            parse_any_date(arguments.trade_date)
            if arguments.trade_date
            else get_next_trade_date(connection, signal_date)
        )

        prediction_frame = load_prediction_dataframe(
            pred_csv=pred_csv,
            signal_date=signal_date,
            trade_date=trade_date,
            model_name=arguments.model_name,
            topk=arguments.topk,
            n_drop=arguments.n_drop,
        )
        inserted_predictions = upsert_dataframe(
            connection,
            arguments.prediction_table,
            prediction_frame,
            key_columns=["signal_date", "instrument", "model_name"],
        )

        previous_date, previous_selected = get_previous_selected(
            connection,
            arguments.prediction_table,
            arguments.model_name,
            signal_date,
        )
        orders_frame = build_orders(
            current_prediction=prediction_frame,
            previous_selected=previous_selected,
            signal_date=signal_date,
            trade_date=trade_date,
            model_name=arguments.model_name,
            topk=arguments.topk,
            n_drop=arguments.n_drop,
            include_hold=arguments.include_hold,
        )

        if not orders_frame.empty:
            upsert_dataframe(
                connection,
                arguments.orders_table,
                orders_frame,
                key_columns=["signal_date", "instrument", "side", "model_name"],
            )

        logger.info(
            "Ingested predictions: rows=%d, selected=%d, signal_date=%s, trade_date=%s",
            inserted_predictions,
            int(prediction_frame["is_selected"].sum()),
            signal_date.isoformat(),
            trade_date.isoformat(),
        )
        if previous_date:
            logger.info("Previous selected date: %s", previous_date.isoformat())
        else:
            logger.info("No previous selected date found; initial day only BUY signals are generated.")

        if not orders_frame.empty:
            output_path = (
                Path(arguments.orders_csv).expanduser().resolve()
                if arguments.orders_csv
                else pred_csv.parent / f"orders_{trade_date.strftime('%Y%m%d')}.csv"
            )
            export_columns = [
                "trade_date",
                "instrument",
                "side",
                "score",
                "rank",
                "model_name",
                "signal_date",
            ]
            orders_frame[export_columns].sort_values(["side", "rank"], ascending=[True, True]).to_csv(
                output_path,
                index=False,
            )
            logger.info("Orders exported: %s", output_path)
            logger.info(
                "Orders summary: BUY=%d, SELL=%d, HOLD=%d",
                int((orders_frame["side"] == "BUY").sum()),
                int((orders_frame["side"] == "SELL").sum()),
                int((orders_frame["side"] == "HOLD").sum()),
            )
        else:
            logger.info("No order changes detected for this signal date.")


def load_execution_dataframe(exec_csv: Path, explicit_trade_date: Optional[str], broker_name: str) -> pd.DataFrame:
    source_frame = pd.read_csv(exec_csv)

    instrument_column = find_first_column(source_frame, ["instrument", "ts_code", "ticker", "symbol"])
    side_column = find_first_column(source_frame, ["side", "action", "direction"])
    qty_column = find_first_column(source_frame, ["filled_qty", "qty", "quantity", "volume", "deal_qty"])
    price_column = find_first_column(source_frame, ["avg_price", "price", "deal_price", "executed_price"])
    status_column = find_first_column(source_frame, ["status", "order_status"])
    order_id_column = find_first_column(source_frame, ["order_id", "external_id", "id"])
    date_column = find_first_column(source_frame, ["trade_date", "date", "executed_at", "timestamp"])

    if not instrument_column or not side_column:
        raise ValueError("Execution CSV must contain instrument and side columns.")

    frame = pd.DataFrame()
    frame["instrument"] = source_frame[instrument_column].map(normalize_instrument)
    frame["side"] = source_frame[side_column].map(normalize_side)

    if qty_column:
        frame["filled_qty"] = pd.to_numeric(source_frame[qty_column], errors="coerce")
    else:
        frame["filled_qty"] = 0.0

    if price_column:
        frame["avg_price"] = pd.to_numeric(source_frame[price_column], errors="coerce")
    else:
        frame["avg_price"] = pd.NA

    if status_column:
        frame["status"] = source_frame[status_column].astype(str).str.upper()
    else:
        frame["status"] = frame["filled_qty"].fillna(0).map(lambda quantity: "FILLED" if quantity > 0 else "UNKNOWN")

    if order_id_column:
        frame["order_id"] = source_frame[order_id_column].astype(str).str.strip()
    else:
        frame["order_id"] = ""

    if explicit_trade_date:
        frame["trade_date"] = parse_any_date(explicit_trade_date)
    elif date_column:
        frame["trade_date"] = pd.to_datetime(source_frame[date_column], errors="coerce").dt.date
    else:
        frame["trade_date"] = date.today()

    frame = frame.dropna(subset=["instrument", "side", "trade_date"]).reset_index(drop=True)
    frame["filled_qty"] = frame["filled_qty"].fillna(0.0)

    missing_order_id = frame["order_id"].isna() | (frame["order_id"].str.len() == 0)
    if missing_order_id.any():
        generated_order_ids = []
        for row_index, row in frame.loc[missing_order_id].iterrows():
            raw_text = (
                f"{row['trade_date']}|{row['instrument']}|{row['side']}|"
                f"{row_index}|{exec_csv.name}|{broker_name}"
            )
            generated_order_ids.append(hashlib.md5(raw_text.encode("utf-8")).hexdigest()[:20])
        frame.loc[missing_order_id, "order_id"] = generated_order_ids

    frame["broker_name"] = broker_name
    frame["source_file"] = str(exec_csv.resolve())
    frame["created_at"] = datetime.now()
    return frame


def run_import_executions(arguments: argparse.Namespace) -> None:
    exec_csv = Path(arguments.exec_csv).expanduser().resolve()
    if not exec_csv.exists():
        raise FileNotFoundError(f"Execution CSV not found: {exec_csv}")

    execution_frame = load_execution_dataframe(
        exec_csv=exec_csv,
        explicit_trade_date=arguments.trade_date,
        broker_name=arguments.broker_name,
    )

    with duckdb.connect(arguments.db_path) as connection:
        ensure_executions_table(connection, arguments.executions_table)
        add_missing_columns(
            connection,
            arguments.executions_table,
            {
                "filled_qty": "DOUBLE",
                "avg_price": "DOUBLE",
                "status": "VARCHAR",
                "broker_name": "VARCHAR",
                "source_file": "VARCHAR",
                "created_at": "TIMESTAMP",
            },
        )
        inserted = upsert_dataframe(
            connection,
            arguments.executions_table,
            execution_frame,
            key_columns=["trade_date", "instrument", "side", "order_id"],
        )

    logger.info(
        "Imported executions: rows=%d, trade_dates=%s",
        inserted,
        ",".join(sorted({d.isoformat() for d in execution_frame["trade_date"].unique()})),
    )


def query_reference_open(
    connection: duckdb.DuckDBPyConnection,
    trade_date: date,
    instruments: Iterable[str],
) -> dict[str, float]:
    if not table_exists(connection, "daily"):
        return {}

    ts_codes = sorted({instrument_to_tscode(instrument) for instrument in instruments})
    if not ts_codes:
        return {}

    placeholders = ", ".join("?" for _ in ts_codes)
    query = (
        "SELECT ts_code, open FROM daily WHERE trade_date = ? "
        f"AND ts_code IN ({placeholders})"
    )
    rows = connection.execute(query, [trade_date, *ts_codes]).fetchall()
    return {
        tscode_to_instrument(ts_code): float(open_price)
        for ts_code, open_price in rows
        if open_price is not None
    }


def run_reconcile(arguments: argparse.Namespace) -> None:
    trade_date = parse_any_date(arguments.trade_date)
    with duckdb.connect(arguments.db_path) as connection:
        ensure_orders_table(connection, arguments.orders_table)
        ensure_executions_table(connection, arguments.executions_table)
        ensure_reconcile_table(connection, arguments.reconcile_table)

        planned_frame = connection.execute(
            f"""
            SELECT signal_date, trade_date, instrument, side, score, rank, model_name
            FROM {validate_identifier(arguments.orders_table)}
            WHERE trade_date = ? AND model_name = ? AND side IN ('BUY', 'SELL')
            """,
            [trade_date, arguments.model_name],
        ).fetchdf()
        if planned_frame.empty:
            raise ValueError(f"No planned orders found for {trade_date} / {arguments.model_name}")

        executed_frame = connection.execute(
            f"""
            SELECT
                trade_date,
                instrument,
                side,
                SUM(COALESCE(filled_qty, 0)) AS filled_qty,
                CASE
                    WHEN SUM(COALESCE(filled_qty, 0)) > 0
                    THEN SUM(COALESCE(filled_qty, 0) * COALESCE(avg_price, 0))
                         / SUM(COALESCE(filled_qty, 0))
                    ELSE NULL
                END AS avg_price,
                STRING_AGG(DISTINCT status, ',') AS status
            FROM {validate_identifier(arguments.executions_table)}
            WHERE trade_date = ? AND side IN ('BUY', 'SELL')
            GROUP BY trade_date, instrument, side
            """,
            [trade_date],
        ).fetchdf()

        planned_frame["instrument"] = planned_frame["instrument"].map(normalize_instrument)
        if not executed_frame.empty:
            executed_frame["instrument"] = executed_frame["instrument"].map(normalize_instrument)
            executed_frame["side"] = executed_frame["side"].map(normalize_side)
        else:
            executed_frame = pd.DataFrame(
                columns=["trade_date", "instrument", "side", "filled_qty", "avg_price", "status"]
            )

        merged = planned_frame.merge(
            executed_frame,
            on=["trade_date", "instrument", "side"],
            how="left",
            suffixes=("", "_exec"),
        )
        merged["executed"] = merged["filled_qty"].fillna(0) > 0
        merged["status"] = merged.apply(
            lambda row: "FILLED"
            if row["executed"]
            else ("REJECTED" if pd.notna(row["status"]) else "MISSED"),
            axis=1,
        )
        merged["note"] = merged["status"].map(
            {
                "FILLED": "planned signal executed",
                "REJECTED": "execution exists but filled_qty=0",
                "MISSED": "planned signal not found in executions",
            }
        )

        planned_keys = set(zip(merged["instrument"], merged["side"]))
        unplanned_rows: list[dict[str, object]] = []
        for _, execution_row in executed_frame.iterrows():
            key = (execution_row["instrument"], execution_row["side"])
            if key in planned_keys:
                continue
            unplanned_rows.append(
                {
                    "signal_date": pd.NaT,
                    "trade_date": trade_date,
                    "instrument": execution_row["instrument"],
                    "side": execution_row["side"],
                    "score": pd.NA,
                    "rank": pd.NA,
                    "model_name": arguments.model_name,
                    "filled_qty": execution_row["filled_qty"],
                    "avg_price": execution_row["avg_price"],
                    "executed": True,
                    "status": "UNPLANNED",
                    "note": "execution exists but no planned signal",
                }
            )

        reference_open = query_reference_open(connection, trade_date, merged["instrument"])
        merged["reference_open"] = merged["instrument"].map(reference_open)

        def calculate_slippage(row: pd.Series) -> Optional[float]:
            if not row["executed"] or pd.isna(row["avg_price"]) or pd.isna(row["reference_open"]):
                return None
            reference_price = float(row["reference_open"])
            average_price = float(row["avg_price"])
            if reference_price == 0:
                return None
            if row["side"] == "BUY":
                return (average_price - reference_price) / reference_price * 10000
            if row["side"] == "SELL":
                return (reference_price - average_price) / reference_price * 10000
            return None

        merged["slippage_bps"] = merged.apply(calculate_slippage, axis=1)
        merged["created_at"] = datetime.now()

        result_columns = [
            "trade_date",
            "instrument",
            "side",
            "model_name",
            "signal_date",
            "score",
            "rank",
            "executed",
            "filled_qty",
            "avg_price",
            "reference_open",
            "slippage_bps",
            "status",
            "note",
            "created_at",
        ]
        final_frame = merged[result_columns].copy()
        if unplanned_rows:
            unplanned_frame = pd.DataFrame(unplanned_rows)
            unplanned_frame["reference_open"] = unplanned_frame["instrument"].map(reference_open)
            unplanned_frame["slippage_bps"] = unplanned_frame.apply(calculate_slippage, axis=1)
            unplanned_frame["created_at"] = datetime.now()
            final_frame = pd.concat([final_frame, unplanned_frame[result_columns]], ignore_index=True)

        upsert_dataframe(
            connection,
            arguments.reconcile_table,
            final_frame,
            key_columns=["trade_date", "instrument", "side", "model_name"],
        )

    planned_count = int((final_frame["status"] != "UNPLANNED").sum())
    filled_count = int((final_frame["status"] == "FILLED").sum())
    missed_count = int((final_frame["status"] == "MISSED").sum())
    rejected_count = int((final_frame["status"] == "REJECTED").sum())
    unplanned_count = int((final_frame["status"] == "UNPLANNED").sum())
    coverage_rate = (filled_count / planned_count) if planned_count else 0.0

    logger.info(
        "Reconcile summary: planned=%d, filled=%d, missed=%d, rejected=%d, unplanned=%d, coverage=%.2f%%",
        planned_count,
        filled_count,
        missed_count,
        rejected_count,
        unplanned_count,
        coverage_rate * 100,
    )

    if arguments.reconcile_csv:
        output_path = Path(arguments.reconcile_csv).expanduser().resolve()
    else:
        output_path = (
            Path.cwd()
            / f"reconcile_{trade_date.strftime('%Y%m%d')}_{arguments.model_name}.csv"
        )
    final_frame.sort_values(["status", "side", "rank"], na_position="last").to_csv(output_path, index=False)
    logger.info("Reconcile detail exported: %s", output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Store Qlib predictions/signals in DuckDB and reconcile with live executions."
    )
    parser.add_argument(
        "--db-path",
        default="/home/tanlu/myworkspace/HATS/data/cn/raw/tushare.duckdb",
        help="DuckDB file path.",
    )
    parser.add_argument(
        "--prediction-table",
        default="qlib_predictions",
        help="Prediction table name.",
    )
    parser.add_argument(
        "--orders-table",
        default="qlib_orders",
        help="Orders table name.",
    )
    parser.add_argument(
        "--executions-table",
        default="qlib_executions",
        help="Executions table name.",
    )
    parser.add_argument(
        "--reconcile-table",
        default="qlib_reconcile",
        help="Reconcile result table name.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser(
        "ingest-pred",
        help="Ingest daily prediction CSV, upsert predictions table, generate orders.",
    )
    ingest_parser.add_argument("--pred-csv", required=True, help="Prediction CSV path.")
    ingest_parser.add_argument("--model-name", required=True, help="Model version tag.")
    ingest_parser.add_argument("--signal-date", help="Signal date YYYY-MM-DD. If omitted, infer from CSV.")
    ingest_parser.add_argument("--trade-date", help="Trade date YYYY-MM-DD. If omitted, infer next trading day.")
    ingest_parser.add_argument("--topk", type=int, default=8, help="Top K for selected stocks.")
    ingest_parser.add_argument("--n-drop", type=int, default=1, help="N drop metadata.")
    ingest_parser.add_argument("--orders-csv", help="Export orders CSV path. Default: orders_YYYYMMDD.csv")
    ingest_parser.add_argument(
        "--include-hold",
        action="store_true",
        help="Include HOLD rows in generated orders.",
    )

    execution_parser = subparsers.add_parser(
        "import-exec",
        help="Import broker execution CSV into executions table.",
    )
    execution_parser.add_argument("--exec-csv", required=True, help="Execution CSV path.")
    execution_parser.add_argument("--trade-date", help="Override trade date YYYY-MM-DD.")
    execution_parser.add_argument("--broker-name", default="manual", help="Broker or source name.")

    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="Reconcile planned orders against live executions for one trade date.",
    )
    reconcile_parser.add_argument("--trade-date", required=True, help="Trade date YYYY-MM-DD.")
    reconcile_parser.add_argument("--model-name", required=True, help="Model version tag.")
    reconcile_parser.add_argument("--reconcile-csv", help="Export detailed reconcile CSV path.")

    return parser


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()

    if arguments.command == "ingest-pred":
        run_ingest_prediction(arguments)
    elif arguments.command == "import-exec":
        run_import_executions(arguments)
    elif arguments.command == "reconcile":
        run_reconcile(arguments)
    else:
        raise ValueError(f"Unsupported command: {arguments.command}")


if __name__ == "__main__":
    main()
