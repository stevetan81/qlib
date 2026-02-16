#!/usr/bin/env python3
"""HATS DDG-DA Workflow — CSI500 元学习滚动训练

基于 qlib.contrib.rolling.ddgda.DDGDA，在 Rolling Retrain 基础上加入
数据分布漂移自适应（DDG-DA）元学习。

用法:
    # 默认 LightGBM, horizon=5 (Phase 2 最优)
    python ddgda_workflow.py run

    # 自定义参数
    python ddgda_workflow.py --horizon=5 --step=20 --sim_task_model=gbdt run
    python ddgda_workflow.py --horizon=3 --sim_task_model=linear run
"""
from pathlib import Path

import fire
import qlib
from qlib.config import REG_CN
from qlib.contrib.rolling.ddgda import DDGDA

DIRNAME = Path(__file__).absolute().resolve().parent
PROVIDER_URI = "/home/tanlu/myworkspace/HATS/data/qlib_export/cn/qlib_bin"


class HATSDDGDAWorkflow(DDGDA):
    CONF_LIST = [
        DIRNAME / "workflow_config_rolling_lgbm.yaml",
    ]
    DEFAULT_CONF = CONF_LIST[0]

    def __init__(self, conf_path=DEFAULT_CONF, horizon=5, step=20, **kwargs):
        conf_path = Path(conf_path)
        super().__init__(
            conf_path=conf_path,
            horizon=horizon,
            step=step,
            working_dir=DIRNAME,
            **kwargs,
        )


if __name__ == "__main__":
    qlib.init(provider_uri=PROVIDER_URI, region=REG_CN)
    fire.Fire(HATSDDGDAWorkflow)
