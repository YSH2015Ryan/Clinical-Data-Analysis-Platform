"""Dummy 基线插件（docs/15 §7 DoD：插件机制验收——零特殊处理经 entry_points 注册）。

多数类基线分类器：fit 记录多数类比例，evaluate 返回多数类准确率。
不进入生产模型候选（T5.6 管理界面可禁用）；存在意义是验证插件机制本身。
"""

from typing import Any, ClassVar


class DummyAdapter:
    key = "dummy"
    name = "Dummy Baseline (plugin mechanism acceptance)"
    version = "0.1.0"
    task_types: ClassVar[list[str]] = ["classification"]
    capabilities: ClassVar[dict[str, Any]] = {
        "shap": False,
        "feature_importance": False,
        "calibration": False,
    }
    default_params: ClassVar[dict[str, Any]] = {}

    def __init__(self) -> None:
        self._majority_rate: float = 0.0

    def fit(self, X: Any, y: Any, params: dict[str, Any]) -> None:
        values = list(y)
        if not values:
            raise ValueError("y 为空")
        self._majority_rate = max(values.count(v) for v in set(values)) / len(values)

    def evaluate(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        values = list(y_val)
        if not values:
            return {"accuracy": 0.0}
        majority = max(set(values), key=values.count)
        correct = sum(1 for v in values if v == majority)
        return {"accuracy": correct / len(values)}

    def explain(self, X_val: Any) -> dict[str, Any] | None:
        return None

    def predict_artifacts(self, X_val: Any, y_val: Any) -> dict[str, Any]:
        return {}
