"""DeepSurv（pycox）可选生存插件（docs/07 §3、docs/20 R2）。

torch/pycox 仅在全量镜像（cdap-worker-full）安装：本模块 import 失败时
注册表按「非法/不可用插件」告警跳过（docs/15 §2），基础镜像不受影响；
全量镜像经 entry_points 正常注册。CPU 训练，统一 seed=42。
"""

from typing import Any, ClassVar

import numpy as np
import pandas as pd
import torch
from pycox.models import CoxPH

from app.engines.comparison.metrics import survival_metrics
from app.plugins.builtin.survival import _split_y, _time_grid


class DeepsurvAdapter:
    key = "deepsurv"
    name = "DeepSurv (pycox, CPU)"
    version = "0.1.0"
    task_types: ClassVar[list[str]] = ["survival"]
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,
        "feature_importance": False,
        "calibration": False,
    }
    default_params: ClassVar[dict[str, Any]] = {
        "epochs": 100,
        "lr": 0.01,
        "batch_size": 64,
        "hidden": [32, 32],
    }

    def fit(self, X: Any, y: Any, params: dict[str, Any]) -> None:
        p = {**self.default_params, **params}
        torch.manual_seed(42)
        torch.set_num_threads(1)  # CPU 限线程（docs/07 §4）
        event, time = _split_y(y)
        self._train_event, self._train_time = event, time
        self._grid = _time_grid(time)

        x = np.asarray(pd.DataFrame(X), dtype=np.float32)
        layers: list[Any] = []
        in_features = x.shape[1]
        for width in p["hidden"]:
            layers += [torch.nn.Linear(in_features, int(width)), torch.nn.ReLU()]
            in_features = int(width)
        layers.append(torch.nn.Linear(in_features, 1))
        net = torch.nn.Sequential(*layers)

        self._model = CoxPH(net, torch.optim.Adam(net.parameters(), lr=p["lr"]))
        durations = time.astype(np.float32)
        events = event.astype(np.float32)
        self._model.fit(
            x,
            (durations, events),
            batch_size=int(p["batch_size"]),
            epochs=int(p["epochs"]),
            verbose=False,
        )
        self._model.compute_baseline_hazards()

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        event, time = _split_y(y_val)
        x = np.asarray(pd.DataFrame(X_val), dtype=np.float32)
        risk = np.asarray(self._model.predict(x), dtype=float).ravel()
        surv_df = self._model.predict_surv_df(x, times=self._grid)
        surv_pred = surv_df.to_numpy().T  # (n_samples, n_times)
        return survival_metrics(
            event_train=self._train_event,
            time_train=self._train_time,
            event_test=event,
            time_test=time,
            risk=risk,
            surv_pred=surv_pred,
            times=self._grid,
        )

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        return None

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return {}
