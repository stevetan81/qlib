#!/usr/bin/env python3
"""Automate daily signal generation and reconciliation with cron."""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import duckdb
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("auto_signal_scheduler")

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / "hats_workflows"
DEFAULT_DB_PATH = Path("/home/tanlu/myworkspace/HATS/data/cn/raw/tushare.duckdb")
DEFAULT_EXEC_DIR = Path("/home/tanlu/myworkspace/HATS/data/executions")
DEFAULT_CONFIG = WORKFLOW_DIR / "config_predict.yaml"
CRON_BEGIN = "# >>> hats_auto_signal >>>"
CRON_END = "# <<< hats_auto_signal <<<"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(name: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid SQL identifier: {name}")
    return name


def parse_trade_date(raw_value: Optional[str], timezone_name: str) -> date:
    if raw_value:
        if not DATE_PATTERN.fullmatch(raw_value):
            raise ValueError(f"Invalid date format: {raw_value}, expected YYYY-MM-DD")
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    timezone = ZoneInfo(timezone_name)
    return datetime.now(timezone).date()


def run_command(command: list[str], cwd: Path = REPO_ROOT) -> None:
    logger.info("Run command: %s", " ".join(command))
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        logger.error("Command failed: %s", " ".join(command))
        if completed.stdout.strip():
            logger.error("stdout:\n%s", completed.stdout.strip())
        if completed.stderr.strip():
            logger.error("stderr:\n%s", completed.stderr.strip())
        raise RuntimeError(f"Command failed with code {completed.returncode}")
    if completed.stdout.strip():
        logger.info("stdout:\n%s", completed.stdout.strip())


def load_predict_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as file_pointer:
        return yaml.safe_load(file_pointer)


def resolve_prediction_output(config_path: Path, trade_date: date) -> Path:
    config = load_predict_config(config_path)
    output = config.get("output", {})
    output_path = Path(output.get("path", "/home/tanlu/myworkspace/HATS/data/predictions"))
    if not output_path.is_absolute():
        output_path = (REPO_ROOT / output_path).resolve()
    filename_pattern = output.get("filename_pattern", "pred_{date}.csv")
    file_name = filename_pattern.format(date=trade_date.strftime("%Y%m%d"))
    return output_path / file_name


def resolve_model_name_from_config(config_path: Path, override_name: str) -> str:
    if override_name != "auto":
        return override_name

    config = load_predict_config(config_path)
    model_path = config.get("model_path")
    if model_path:
        model_file = Path(model_path)
        if not model_file.is_absolute():
            model_file = (REPO_ROOT / model_file).resolve()
        if model_file.is_symlink():
            model_file = model_file.resolve()
        if model_file.name:
            return model_file.stem
    return "model_auto"


def resolve_model_name_from_orders(
    db_path: Path,
    orders_table: str,
    trade_date: date,
    override_name: str,
) -> str:
    if override_name != "auto":
        return override_name

    orders_table = validate_identifier(orders_table)
    query = (
        f"SELECT model_name, COUNT(*) AS count FROM {orders_table} "
        "WHERE trade_date = ? GROUP BY model_name ORDER BY count DESC LIMIT 1"
    )

    with duckdb.connect(str(db_path)) as connection:
        result = connection.execute(query, [trade_date]).fetchone()
    if not result or not result[0]:
        raise ValueError(f"No orders found for trade_date={trade_date} to infer model_name.")
    return str(result[0])


def run_daily_pipeline(arguments: argparse.Namespace) -> None:
    trade_date = parse_trade_date(arguments.date, arguments.timezone)
    trade_date_str = trade_date.isoformat()
    logger.info("Daily pipeline start for trade_date=%s", trade_date_str)

    resolved_model_name = resolve_model_name_from_config(
        Path(arguments.predict_config).resolve(),
        arguments.model_name,
    )
    predict_command = [
        sys.executable,
        str(WORKFLOW_DIR / "run_workflow.py"),
        "--mode",
        "predict",
        "--config",
        str(Path(arguments.predict_config).resolve()),
        "--date",
        trade_date_str,
    ]
    run_command(predict_command)

    prediction_csv = resolve_prediction_output(Path(arguments.predict_config).resolve(), trade_date)
    if not prediction_csv.exists():
        raise FileNotFoundError(f"Prediction CSV not found: {prediction_csv}")

    ingest_command = [
        sys.executable,
        str(WORKFLOW_DIR / "signal_duckdb_pipeline.py"),
        "--db-path",
        str(Path(arguments.db_path).resolve()),
        "--prediction-table",
        arguments.prediction_table,
        "--orders-table",
        arguments.orders_table,
        "--executions-table",
        arguments.executions_table,
        "--reconcile-table",
        arguments.reconcile_table,
        "ingest-pred",
        "--pred-csv",
        str(prediction_csv),
        "--model-name",
        resolved_model_name,
        "--signal-date",
        trade_date_str,
        "--topk",
        str(arguments.topk),
        "--n-drop",
        str(arguments.n_drop),
    ]
    if arguments.orders_csv:
        ingest_command.extend(["--orders-csv", str(Path(arguments.orders_csv).resolve())])
    run_command(ingest_command)
    logger.info("Daily pipeline completed for trade_date=%s, model_name=%s", trade_date_str, resolved_model_name)


def resolve_execution_csv(arguments: argparse.Namespace, trade_date: date) -> Path:
    if arguments.exec_csv:
        return Path(arguments.exec_csv).expanduser().resolve()
    exec_dir = Path(arguments.exec_dir).expanduser().resolve()
    file_name = arguments.exec_pattern.format(date=trade_date.strftime("%Y%m%d"))
    return exec_dir / file_name


def run_reconcile_pipeline(arguments: argparse.Namespace) -> None:
    trade_date = parse_trade_date(arguments.date, arguments.timezone)
    trade_date_str = trade_date.isoformat()
    logger.info("Reconcile pipeline start for trade_date=%s", trade_date_str)

    execution_csv = resolve_execution_csv(arguments, trade_date)
    if not execution_csv.exists():
        if arguments.strict_exec:
            raise FileNotFoundError(f"Execution CSV not found: {execution_csv}")
        logger.warning("Execution CSV not found, skip reconcile: %s", execution_csv)
        return

    resolved_model_name = resolve_model_name_from_orders(
        db_path=Path(arguments.db_path).resolve(),
        orders_table=arguments.orders_table,
        trade_date=trade_date,
        override_name=arguments.model_name,
    )

    import_command = [
        sys.executable,
        str(WORKFLOW_DIR / "signal_duckdb_pipeline.py"),
        "--db-path",
        str(Path(arguments.db_path).resolve()),
        "--prediction-table",
        arguments.prediction_table,
        "--orders-table",
        arguments.orders_table,
        "--executions-table",
        arguments.executions_table,
        "--reconcile-table",
        arguments.reconcile_table,
        "import-exec",
        "--exec-csv",
        str(execution_csv),
        "--trade-date",
        trade_date_str,
        "--broker-name",
        arguments.broker_name,
    ]
    run_command(import_command)

    reconcile_command = [
        sys.executable,
        str(WORKFLOW_DIR / "signal_duckdb_pipeline.py"),
        "--db-path",
        str(Path(arguments.db_path).resolve()),
        "--prediction-table",
        arguments.prediction_table,
        "--orders-table",
        arguments.orders_table,
        "--executions-table",
        arguments.executions_table,
        "--reconcile-table",
        arguments.reconcile_table,
        "reconcile",
        "--trade-date",
        trade_date_str,
        "--model-name",
        resolved_model_name,
    ]
    if arguments.reconcile_csv:
        reconcile_command.extend(["--reconcile-csv", str(Path(arguments.reconcile_csv).resolve())])
    run_command(reconcile_command)
    logger.info("Reconcile pipeline completed for trade_date=%s, model_name=%s", trade_date_str, resolved_model_name)


def read_crontab(cron_user: Optional[str]) -> str:
    command = ["crontab"]
    if cron_user:
        command.extend(["-u", cron_user])
    command.append("-l")
    process = subprocess.run(command, capture_output=True, text=True)
    if process.returncode != 0:
        return ""
    return process.stdout


def write_crontab(content: str, cron_user: Optional[str]) -> None:
    command = ["crontab"]
    if cron_user:
        command.extend(["-u", cron_user])
    command.append("-")
    process = subprocess.run(command, input=content, text=True, capture_output=True)
    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip() or "unknown error"
        raise RuntimeError(f"Failed to update crontab: {message}")


def build_cron_block(arguments: argparse.Namespace) -> str:
    python_exec = sys.executable
    repo_root = str(REPO_ROOT)
    logs_dir = Path(arguments.logs_dir).expanduser().resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)
    daily_log = logs_dir / "auto_signal_daily.log"
    reconcile_log = logs_dir / "auto_signal_reconcile.log"

    daily_cmd = (
        f"cd {repo_root} && "
        f"{python_exec} hats_workflows/auto_signal_scheduler.py run-daily "
        f"--predict-config {Path(arguments.predict_config).resolve()} "
        f"--db-path {Path(arguments.db_path).resolve()} "
        f"--model-name {arguments.model_name} "
        f"--topk {arguments.topk} --n-drop {arguments.n_drop} "
        f"--prediction-table {arguments.prediction_table} "
        f"--orders-table {arguments.orders_table} "
        f"--executions-table {arguments.executions_table} "
        f"--reconcile-table {arguments.reconcile_table} "
        f"--timezone {arguments.timezone} "
        f">> {daily_log} 2>&1"
    )

    reconcile_cmd = (
        f"cd {repo_root} && "
        f"{python_exec} hats_workflows/auto_signal_scheduler.py run-reconcile "
        f"--db-path {Path(arguments.db_path).resolve()} "
        f"--model-name {arguments.model_name} "
        f"--prediction-table {arguments.prediction_table} "
        f"--orders-table {arguments.orders_table} "
        f"--executions-table {arguments.executions_table} "
        f"--reconcile-table {arguments.reconcile_table} "
        f"--exec-dir {Path(arguments.exec_dir).resolve()} "
        f"--exec-pattern {arguments.exec_pattern} "
        f"--broker-name {arguments.broker_name} "
        f"--timezone {arguments.timezone} "
        f">> {reconcile_log} 2>&1"
    )

    lines = [
        CRON_BEGIN,
        f"CRON_TZ={arguments.timezone}",
        f"{arguments.daily_cron} {daily_cmd}",
        f"{arguments.reconcile_cron} {reconcile_cmd}",
        CRON_END,
    ]
    return "\n".join(lines)


def upsert_cron_block(existing: str, block: str) -> str:
    pattern = re.compile(
        rf"{re.escape(CRON_BEGIN)}.*?{re.escape(CRON_END)}\n?",
        flags=re.DOTALL,
    )
    cleaned = re.sub(pattern, "", existing).strip()
    if cleaned:
        return f"{cleaned}\n\n{block}\n"
    return f"{block}\n"


def install_cron(arguments: argparse.Namespace) -> None:
    existing = read_crontab(arguments.cron_user)
    block = build_cron_block(arguments)
    updated = upsert_cron_block(existing, block)
    write_crontab(updated, arguments.cron_user)
    logger.info("Cron installed/updated for user=%s.", arguments.cron_user or "<current>")
    logger.info("Schedule daily=%s, reconcile=%s, timezone=%s", arguments.daily_cron, arguments.reconcile_cron, arguments.timezone)


def print_cron(arguments: argparse.Namespace) -> None:
    block = build_cron_block(arguments)
    print(block)


def remove_cron(arguments: argparse.Namespace) -> None:
    existing = read_crontab(arguments.cron_user)
    updated = upsert_cron_block(existing, "")
    updated = updated.strip() + ("\n" if updated.strip() else "")
    write_crontab(updated, arguments.cron_user)
    logger.info("Cron block removed for user=%s.", arguments.cron_user or "<current>")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automate daily signal pipeline and reconciliation.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    daily_parser = subparsers.add_parser("run-daily", help="Run daily prediction -> ingest -> orders pipeline.")
    daily_parser.add_argument("--date", help="Trade date YYYY-MM-DD. Default: today in timezone.")
    daily_parser.add_argument("--timezone", default="Asia/Shanghai", help="Timezone for default date.")
    daily_parser.add_argument("--predict-config", default=str(DEFAULT_CONFIG), help="Predict YAML config path.")
    daily_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="DuckDB path.")
    daily_parser.add_argument("--model-name", required=True, help="Model version tag.")
    daily_parser.add_argument("--topk", type=int, default=8, help="Top K for signals.")
    daily_parser.add_argument("--n-drop", type=int, default=1, help="Drop count metadata.")
    daily_parser.add_argument("--orders-csv", help="Optional exported orders CSV path.")
    daily_parser.add_argument("--prediction-table", default="qlib_predictions")
    daily_parser.add_argument("--orders-table", default="qlib_orders")
    daily_parser.add_argument("--executions-table", default="qlib_executions")
    daily_parser.add_argument("--reconcile-table", default="qlib_reconcile")

    reconcile_parser = subparsers.add_parser("run-reconcile", help="Import executions and reconcile.")
    reconcile_parser.add_argument("--date", help="Trade date YYYY-MM-DD. Default: today in timezone.")
    reconcile_parser.add_argument("--timezone", default="Asia/Shanghai", help="Timezone for default date.")
    reconcile_parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="DuckDB path.")
    reconcile_parser.add_argument("--model-name", required=True, help="Model version tag.")
    reconcile_parser.add_argument("--exec-csv", help="Broker execution CSV path.")
    reconcile_parser.add_argument("--exec-dir", default=str(DEFAULT_EXEC_DIR), help="Execution CSV directory.")
    reconcile_parser.add_argument("--exec-pattern", default="executions_{date}.csv", help="Execution filename pattern.")
    reconcile_parser.add_argument("--broker-name", default="broker_a", help="Broker/source name.")
    reconcile_parser.add_argument("--strict-exec", action="store_true", help="Fail if execution CSV is missing.")
    reconcile_parser.add_argument("--reconcile-csv", help="Optional exported reconcile CSV path.")
    reconcile_parser.add_argument("--prediction-table", default="qlib_predictions")
    reconcile_parser.add_argument("--orders-table", default="qlib_orders")
    reconcile_parser.add_argument("--executions-table", default="qlib_executions")
    reconcile_parser.add_argument("--reconcile-table", default="qlib_reconcile")

    cron_defaults = {
        "daily_cron": "5 16 * * 1-5",
        "reconcile_cron": "35 16 * * 1-5",
        "timezone": "Asia/Shanghai",
        "predict_config": str(DEFAULT_CONFIG),
        "db_path": str(DEFAULT_DB_PATH),
        "model_name": "auto",
        "topk": 8,
        "n_drop": 1,
        "exec_dir": str(DEFAULT_EXEC_DIR),
        "exec_pattern": "executions_{date}.csv",
        "broker_name": "broker_a",
        "logs_dir": str(WORKFLOW_DIR / "logs"),
        "prediction_table": "qlib_predictions",
        "orders_table": "qlib_orders",
        "executions_table": "qlib_executions",
        "reconcile_table": "qlib_reconcile",
    }

    cron_parser = subparsers.add_parser("install-cron", help="Install or update cron jobs.")
    cron_parser.add_argument("--daily-cron", default=cron_defaults["daily_cron"], help="Cron expression for daily pipeline.")
    cron_parser.add_argument("--reconcile-cron", default=cron_defaults["reconcile_cron"], help="Cron expression for reconcile pipeline.")
    cron_parser.add_argument("--timezone", default=cron_defaults["timezone"])
    cron_parser.add_argument("--predict-config", default=cron_defaults["predict_config"])
    cron_parser.add_argument("--db-path", default=cron_defaults["db_path"])
    cron_parser.add_argument("--model-name", default=cron_defaults["model_name"])
    cron_parser.add_argument("--topk", type=int, default=cron_defaults["topk"])
    cron_parser.add_argument("--n-drop", type=int, default=cron_defaults["n_drop"])
    cron_parser.add_argument("--exec-dir", default=cron_defaults["exec_dir"])
    cron_parser.add_argument("--exec-pattern", default=cron_defaults["exec_pattern"])
    cron_parser.add_argument("--broker-name", default=cron_defaults["broker_name"])
    cron_parser.add_argument("--logs-dir", default=cron_defaults["logs_dir"])
    cron_parser.add_argument("--prediction-table", default=cron_defaults["prediction_table"])
    cron_parser.add_argument("--orders-table", default=cron_defaults["orders_table"])
    cron_parser.add_argument("--executions-table", default=cron_defaults["executions_table"])
    cron_parser.add_argument("--reconcile-table", default=cron_defaults["reconcile_table"])
    cron_parser.add_argument("--cron-user", help="Target crontab user.")

    print_parser = subparsers.add_parser("print-cron", help="Print cron block without installing.")
    print_parser.add_argument("--daily-cron", default=cron_defaults["daily_cron"])
    print_parser.add_argument("--reconcile-cron", default=cron_defaults["reconcile_cron"])
    print_parser.add_argument("--timezone", default=cron_defaults["timezone"])
    print_parser.add_argument("--predict-config", default=cron_defaults["predict_config"])
    print_parser.add_argument("--db-path", default=cron_defaults["db_path"])
    print_parser.add_argument("--model-name", default=cron_defaults["model_name"])
    print_parser.add_argument("--topk", type=int, default=cron_defaults["topk"])
    print_parser.add_argument("--n-drop", type=int, default=cron_defaults["n_drop"])
    print_parser.add_argument("--exec-dir", default=cron_defaults["exec_dir"])
    print_parser.add_argument("--exec-pattern", default=cron_defaults["exec_pattern"])
    print_parser.add_argument("--broker-name", default=cron_defaults["broker_name"])
    print_parser.add_argument("--logs-dir", default=cron_defaults["logs_dir"])
    print_parser.add_argument("--prediction-table", default=cron_defaults["prediction_table"])
    print_parser.add_argument("--orders-table", default=cron_defaults["orders_table"])
    print_parser.add_argument("--executions-table", default=cron_defaults["executions_table"])
    print_parser.add_argument("--reconcile-table", default=cron_defaults["reconcile_table"])

    remove_parser = subparsers.add_parser("remove-cron", help="Remove installed cron block.")
    remove_parser.add_argument("--cron-user", help="Target crontab user.")
    return parser


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()

    if arguments.command == "run-daily":
        run_daily_pipeline(arguments)
        return
    if arguments.command == "run-reconcile":
        run_reconcile_pipeline(arguments)
        return
    if arguments.command == "install-cron":
        install_cron(arguments)
        return
    if arguments.command == "print-cron":
        print_cron(arguments)
        return
    if arguments.command == "remove-cron":
        remove_cron(arguments)
        return

    raise ValueError(f"Unsupported command: {arguments.command}")


if __name__ == "__main__":
    main()
