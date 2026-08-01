"""T7.3 图表 PNG 装配单测（docs/09 §3 单数据源；docs/10 §3）。

每种 ChartAsset kind 由同一数据 JSON 渲染出非空 PNG；无数据/未知 kind → None。
"""

from app.engines.reporting.chart_png import chart_to_b64, chart_to_png

PNG_MAGIC = b"\x89PNG"


def _charts() -> list[dict]:
    return [
        {
            "kind": "roc",
            "data": {
                "series": [
                    {"model_key": "logreg", "fpr": [0, 0.1, 1], "tpr": [0, 0.9, 1], "auc": 0.8}
                ]
            },
        },
        {
            "kind": "calibration",
            "data": {
                "series": [
                    {
                        "model_key": "logreg",
                        "prob_true": [0.1, 0.9],
                        "prob_pred": [0.2, 0.8],
                        "brier": 0.15,
                    }
                ]
            },
        },
        {
            "kind": "dca",
            "data": {
                "series": [
                    {"model_key": "logreg", "thresholds": [0.3, 0.7], "net_benefit": [0.4, 0.2]}
                ],
                "treat_all": {"thresholds": [0.01, 0.99], "net_benefit": [0.49, -0.49]},
                "prevalence": 0.5,
            },
        },
        {
            "kind": "confusion_matrix",
            "data": {
                "models": [{"model_key": "logreg", "labels": [0, 1], "matrix": [[40, 10], [5, 45]]}]
            },
        },
        {
            "kind": "km",
            "data": {
                "series": [
                    {
                        "model_key": "coxph",
                        "group": "低风险",
                        "times": [1, 2],
                        "survival": [0.9, 0.8],
                    },
                    {
                        "model_key": "coxph",
                        "group": "高风险",
                        "times": [1, 2],
                        "survival": [0.7, 0.5],
                    },
                ]
            },
        },
        {
            "kind": "cindex_forest",
            "data": {
                "rows": [{"model_key": "coxph", "c_index": 0.7, "ci_lower": 0.6, "ci_upper": 0.8}]
            },
        },
        {
            "kind": "hr_forest",
            "data": {
                "models": [
                    {
                        "model_key": "coxph",
                        "rows": [
                            {
                                "feature": "age",
                                "hr": 1.5,
                                "ci_lower": 1.1,
                                "ci_upper": 2.0,
                                "p_value": 0.01,
                            }
                        ],
                    }
                ]
            },
        },
        {
            "kind": "feature_importance",
            "data": {
                "features": ["age", "bmi"],
                "series": [{"model_key": "logreg", "values": [1.0, 0.4]}],
            },
        },
        {
            "kind": "prediction_scatter",
            "data": {
                "series": [
                    {"model_key": "lasso", "y_true": [1.0, 2.0], "y_pred": [1.1, 1.9], "rmse": 2.5}
                ]
            },
        },
    ]


class TestChartPng:
    def test_all_kinds_render(self) -> None:
        for chart in _charts():
            png = chart_to_png(chart)
            assert png is not None, chart["kind"]
            assert png.startswith(PNG_MAGIC)
            assert len(png) > 500

    def test_b64_roundtrip(self) -> None:
        chart = _charts()[0]
        b64 = chart_to_b64(chart)
        assert b64 is not None and len(b64) > 100

    def test_empty_data_returns_none(self) -> None:
        assert chart_to_png({"kind": "roc", "data": {"series": []}}) is None
        assert chart_to_png({"kind": "unknown_kind", "data": {}}) is None

    def test_malformed_data_no_crash(self) -> None:
        assert chart_to_png({"kind": "confusion_matrix", "data": {"models": []}}) is None
