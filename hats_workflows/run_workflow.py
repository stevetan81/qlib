#!/usr/bin/env python3
# MIT License
# Copyright (c) 2025 stevetan81

"""HATS Qlib 工作流入口。

支持训练和预测两种模式：
    - train: 使用 CSI1000 训练 LightGBM 模型
    - predict: 对全市场进行预测

用法:
    python run_workflow.py --mode train      # 训练模式
    python run_workflow.py --mode predict    # 预测模式
    python run_workflow.py --mode predict --date 2026-01-30  # 指定日期预测
"""

import argparse
import logging
import pickle
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 工作流目录
WORKFLOW_DIR = Path(__file__).parent
MODELS_DIR = WORKFLOW_DIR / "models"


def load_config(config_path: str) -> dict:
    """加载 YAML 配置文件。"""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def init_qlib(config: dict):
    """初始化 Qlib。"""
    import qlib
    from qlib.config import REG_CN

    qlib_init = config.get("qlib_init", {})
    provider_uri = qlib_init.get("provider_uri", "~/.qlib/qlib_data/cn_data")
    region = qlib_init.get("region", "cn")

    logger.info(f"Initializing Qlib with provider_uri: {provider_uri}")

    qlib.init(
        provider_uri=provider_uri,
        region=REG_CN if region == "cn" else region
    )


def run_training(config_path: str = None):
    """执行模型训练。

    Args:
        config_path: 配置文件路径
    """
    if config_path is None:
        config_path = WORKFLOW_DIR / "config_train.yaml"

    logger.info("=" * 60)
    logger.info("Starting Model Training")
    logger.info("=" * 60)

    config = load_config(config_path)
    init_qlib(config)

    from qlib.utils import init_instance_by_config
    from qlib.workflow import R
    from qlib.workflow.record_temp import SignalRecord, SigAnaRecord

    # 创建数据集
    logger.info("Creating dataset...")
    dataset = init_instance_by_config(config["dataset_config"])

    # 创建模型
    logger.info("Creating model...")
    model = init_instance_by_config(config["model_config"])

    # 训练
    logger.info("Training model...")
    with R.start(experiment_name="hats_lgbm_train"):
        model.fit(dataset)

        # 预测验证集
        pred = model.predict(dataset)

        # 计算 Rank IC
        from scipy import stats
        import numpy as np

        test_label = dataset.prepare("test", col_set="label")
        test_pred = pred.loc[test_label.index]

        rank_ic_list = []
        for date in test_label.index.get_level_values(0).unique():
            day_label = test_label.loc[date].values.flatten()
            day_pred = test_pred.loc[date].values.flatten()

            # 过滤 NaN
            mask = ~(np.isnan(day_label) | np.isnan(day_pred))
            if mask.sum() > 10:
                corr, _ = stats.spearmanr(day_label[mask], day_pred[mask])
                if not np.isnan(corr):
                    rank_ic_list.append(corr)

        rank_ic = np.mean(rank_ic_list) if rank_ic_list else 0
        rank_ic_std = np.std(rank_ic_list) if rank_ic_list else 0
        rank_ic_ir = rank_ic / rank_ic_std if rank_ic_std > 0 else 0

        logger.info(f"Rank IC: {rank_ic:.4f} ± {rank_ic_std:.4f}")
        logger.info(f"Rank IC IR: {rank_ic_ir:.4f}")

        # 保存模型
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        model_name = f"lgbm_csi1000_{datetime.now().strftime('%Y%m%d')}.pkl"
        model_path = MODELS_DIR / model_name

        with open(model_path, 'wb') as f:
            pickle.dump(model, f)

        logger.info(f"Model saved: {model_path}")

        # 更新 current 软链接
        current_link = MODELS_DIR / "current"
        if current_link.is_symlink():
            current_link.unlink()
        current_link.symlink_to(model_name)

        logger.info(f"Current model updated: current -> {model_name}")

    logger.info("=" * 60)
    logger.info("Training Completed")
    logger.info(f"Rank IC: {rank_ic:.4f}")
    logger.info("=" * 60)

    return rank_ic


def run_prediction(config_path: str = None, pred_date: str = None):
    """执行预测。

    Args:
        config_path: 配置文件路径
        pred_date: 预测日期，默认今天
    """
    if config_path is None:
        config_path = WORKFLOW_DIR / "config_predict.yaml"

    if pred_date is None:
        pred_date = datetime.now().strftime("%Y-%m-%d")

    logger.info("=" * 60)
    logger.info(f"Starting Prediction for {pred_date}")
    logger.info("=" * 60)

    config = load_config(config_path)
    init_qlib(config)

    # 加载模型
    model_path = Path(config.get("model_path", MODELS_DIR / "current"))
    if model_path.is_symlink():
        model_path = model_path.resolve()

    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    logger.info(f"Loading model: {model_path}")
    with open(model_path, 'rb') as f:
        model = pickle.load(f)

    # 创建数据集
    from qlib.utils import init_instance_by_config
    from qlib.data import D

    # 修改配置中的日期范围
    handler_config = config["data_handler_config"].copy()
    handler_config["start_time"] = pred_date
    handler_config["end_time"] = pred_date

    dataset_config = config["dataset_config"].copy()
    dataset_config["kwargs"]["handler"]["kwargs"] = handler_config
    dataset_config["kwargs"]["segments"] = {"predict": [pred_date, pred_date]}

    logger.info("Creating dataset...")
    dataset = init_instance_by_config(dataset_config)

    # 预测
    logger.info("Running prediction...")
    pred = model.predict(dataset)

    if pred.empty:
        logger.warning("No predictions generated")
        return None

    # 格式化输出
    pred_df = pred.reset_index()
    pred_df.columns = ["datetime", "instrument", "score"]
    pred_df["rank"] = pred_df["score"].rank(ascending=False, method="min").astype(int)
    pred_df = pred_df.sort_values("rank")

    # 保存预测结果
    output_config = config.get("output", {})
    output_dir = Path(output_config.get("path", "/home/tanlu/myworkspace/HATS/data/predictions"))
    output_dir.mkdir(parents=True, exist_ok=True)

    filename_pattern = output_config.get("filename_pattern", "pred_{date}.csv")
    output_file = output_dir / filename_pattern.format(date=pred_date.replace("-", ""))

    pred_df.to_csv(output_file, index=False)
    logger.info(f"Predictions saved: {output_file}")

    # 显示 Top 20
    logger.info("\nTop 20 predictions:")
    logger.info(pred_df.head(20).to_string(index=False))

    logger.info("=" * 60)
    logger.info(f"Prediction Completed: {len(pred_df)} stocks")
    logger.info("=" * 60)

    return pred_df


def main():
    parser = argparse.ArgumentParser(description="HATS Qlib 工作流")
    parser.add_argument("--mode", type=str, required=True, choices=["train", "predict"],
                        help="运行模式: train 或 predict")
    parser.add_argument("--config", type=str, help="配置文件路径")
    parser.add_argument("--date", type=str, help="预测日期 (仅 predict 模式)")

    args = parser.parse_args()

    try:
        if args.mode == "train":
            rank_ic = run_training(args.config)
            print(f"Rank IC: {rank_ic:.4f}")
        elif args.mode == "predict":
            run_prediction(args.config, args.date)
    except Exception as e:
        logger.error(f"Workflow failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
