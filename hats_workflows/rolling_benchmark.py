#!/usr/bin/env python3
"""HATS Rolling Benchmark — CSI500 滚动训练入口

基于 qlib.contrib.rolling.base.Rolling 基类，适配 CSI500 股票池。

用法:
    # 默认 LightGBM, horizon=3 (T+3, Phase 1.2 最优标签)
    python rolling_benchmark.py run

    # 自定义 horizon
    python rolling_benchmark.py --horizon=1 run
    python rolling_benchmark.py --horizon=5 run
    python rolling_benchmark.py --horizon=10 run

    # 自定义 step (重训频率)
    python rolling_benchmark.py --horizon=3 --step=10 run
"""
import os
from pathlib import Path

import fire
import qlib
from qlib.config import REG_CN
from qlib.contrib.rolling.base import Rolling

DIRNAME = Path(__file__).absolute().resolve().parent
PROVIDER_URI = "/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin"


class HATSRollingBenchmark(Rolling):
    CONF_LIST = [
        DIRNAME / "workflow_config_rolling_lgbm.yaml",
    ]
    DEFAULT_CONF = CONF_LIST[0]

    def __init__(self, conf_path=DEFAULT_CONF, horizon=3, step=20, **kwargs):
        conf_path = Path(conf_path)
        super().__init__(conf_path=conf_path, horizon=horizon, step=step, **kwargs)


if __name__ == "__main__":
    qlib.init(provider_uri=PROVIDER_URI, region=REG_CN)
    fire.Fire(HATSRollingBenchmark)
