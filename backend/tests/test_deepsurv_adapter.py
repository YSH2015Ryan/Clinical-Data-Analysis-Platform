"""T5.6 DeepSurv 适配器（pycox, CPU）（docs/07 §3、docs/20 R2）。

DeepSurv 为可选模型：torch/pycox 仅在全量镜像（cdap-worker-full）安装。
- 基础镜像：entry point 加载即 ImportError → 注册表告警跳过（不注册）；
- 全量镜像：正常注册并跑通 CPU 训练。
本测试文件在无 torch/pycox 环境整体 skip。
"""

import pytest

torch = pytest.importorskip("torch", reason="DeepSurv 需全量镜像（torch/pycox）")
pytest.importorskip("pycox", reason="DeepSurv 需全量镜像（torch/pycox）")

import json  # noqa: E402
from typing import Any  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from app.engines.model_registry import ModelRegistry  # noqa: E402
from sksurv.util import Surv  # noqa: E402


def _survival_data(seed: int = 42) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    n = 120
    X = pd.DataFrame(
        {
            "age": rng.normal(60, 10, n),
            "treatment": rng.integers(0, 2, n).astype(float),
            "biomarker": rng.normal(0, 1, n),
        }
    )
    linear = 0.05 * X["age"] + 1.0 * X["treatment"] - 0.8 * X["biomarker"]
    scale = 20.0 / np.exp(linear - linear.mean())
    time = rng.exponential(scale.to_numpy()) + 1.0
    censor = rng.exponential(80.0, n)
    observed = np.minimum(time, censor)
    y = Surv.from_arrays(time <= censor, observed)
    return {"X": X, "y": y}


class TestDeepSurvAdapter:
    def test_registered_in_full_image(self) -> None:
        registry = ModelRegistry()
        registry.load()
        adapter = registry.get("deepsurv")
        assert adapter is not None
        assert adapter.task_types == ["survival"]

    def test_cpu_training_completes(self) -> None:
        d = _survival_data()
        registry = ModelRegistry()
        registry.load()
        adapter = registry.get("deepsurv")
        adapter.fit(d["X"], d["y"], {"epochs": 5, "batch_size": 32, "hidden": [16]})
        m = adapter.evaluate(d["X"], d["y"])
        assert 0.0 <= m["c_index"] <= 1.0
        assert "ibs" in m
        json.dumps(m)
