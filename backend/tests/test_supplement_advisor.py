"""T6.14 数据缺口建议引擎测试（路线图 T6.14；红线 8 数值全部真实计算）。

判断/计算全部确定性规则；每条建议附 basis 依据串（含真实数值与公式），
可展开核对。① EPV 不足：缺口事件=⌈10×特征数−阳性数⌉，需补样本量=
⌈缺口事件/阳性率⌉；阳性率=0 时不出 N（那是编造），改提示确认结局定义。
"""

from typing import Any

from app.engines.supplement_advisor import advise_supplements


def _eda(n_rows: int, n_features: int, n_events: int | None) -> dict[str, Any]:
    epv = round(n_events / n_features, 2) if n_events is not None and n_features else None
    return {
        "row_count": n_rows,
        "column_count": n_features + 1,
        "missing": {"complete_case_ratio": 0.9},
        "sample_size": {
            "n_rows": n_rows,
            "n_features": n_features,
            "event_column": "outcome" if n_events is not None else None,
            "n_events": n_events,
            "epv": epv,
            "epv_adequate": (epv is not None and epv >= 10) or None,
        },
    }


def _research(research_type: str = "cross_sectional") -> dict[str, Any]:
    return {"research_type": research_type, "confidence": 0.8, "recommended_models": []}


class TestEpvDeficit:
    """① EPV 不足（Peduzzi 1996：每变量事件数 ≥10）。"""

    def test_epv_deficit_real_numbers(self) -> None:
        # 92 例、40 特征、28 阳性 → EPV=0.7（实据场景）
        plan = advise_supplements(None, _eda(92, 40, 28), [], _research())
        item = next(i for i in plan["items"] if i["deficit_type"] == "epv")
        assert item["current"]["epv"] == 0.7
        assert item["current"]["n_events"] == 28
        assert item["gap"]["missing_events"] == 372  # ⌈10×40 − 28⌉
        # 阳性率 28/92 ≈ 0.3043 → ⌈372 / 0.3043⌉ = 1223
        assert item["gap"]["additional_rows"] == 1223
        assert "372" in item["basis"] and "1223" in item["basis"]
        assert "28/92" in item["basis"]  # 依据串含真实阳性率来源

    def test_boundary_epv_10_not_triggered(self) -> None:
        # 400 特征 4000 阳性 → EPV 恰 10.0 不触发
        plan = advise_supplements(None, _eda(40000, 400, 4000), [], _research())
        assert not any(i["deficit_type"] == "epv" for i in plan["items"])

    def test_boundary_epv_just_below_10(self) -> None:
        # 10 特征 99 阳性 → EPV=9.9 触发，缺口=1
        plan = advise_supplements(None, _eda(1000, 10, 99), [], _research())
        item = next(i for i in plan["items"] if i["deficit_type"] == "epv")
        assert item["gap"]["missing_events"] == 1

    def test_zero_prevalence_no_fabricated_n(self) -> None:
        # 阳性率=0：折算 N 无意义，必须改为结局定义提示，不得出数字
        plan = advise_supplements(None, _eda(500, 20, 0), [], _research())
        item = next(i for i in plan["items"] if i["deficit_type"] == "epv")
        assert item["gap"]["additional_rows"] is None
        assert "结局" in item["suggestion"]

    def test_no_event_column_not_applicable(self) -> None:
        # 无二值结局列 → 无法定义 EPV，不误报
        plan = advise_supplements(None, _eda(100, 10, None), [], _research())
        assert not any(i["deficit_type"] == "epv" for i in plan["items"])

    def test_healthy_dataset_no_items(self) -> None:
        plan = advise_supplements(None, _eda(10000, 20, 5000), [], _research())
        assert plan["items"] == []
        assert plan["overall"]


class TestClassImbalance:
    """② 类别不均衡:少数类占比 <10%(教科书阈值;① 已触发时去重不报)。

    需补少数类样本=⌈多数类/9⌉−少数类(假设:多数类不变,目标占比 10% 为本规则阈值,
    依据串明示该假设)。EPV 充足(①未触发)才可能报,避免与① 重复同一组缺口数字。
    """

    def test_imbalance_low_prevalence_real_numbers(self) -> None:
        # 20000 例、20 特征、1000 阳性:EPV=50 充足,但阳性率 5%<10%
        plan = advise_supplements(None, _eda(20000, 20, 1000), [], _research())
        item = next(i for i in plan["items"] if i["deficit_type"] == "imbalance")
        assert item["current"]["minority_rate"] == 0.05
        assert item["current"]["minority_label"] == "阳性"
        # ⌈19000/9⌉−1000 = 2112−1000 = 1112
        assert item["gap"]["additional_minority_rows"] == 1112
        assert "1112" in item["basis"] and "19000/9" in item["basis"]
        assert "1000/20000" in item["basis"]  # 依据串含真实占比来源

    def test_imbalance_high_prevalence_symmetric(self) -> None:
        # 阳性率 95%:少数类是阴性 500 例,同样触发(对称判定)
        plan = advise_supplements(None, _eda(10000, 10, 9500), [], _research())
        item = next(i for i in plan["items"] if i["deficit_type"] == "imbalance")
        assert item["current"]["minority_label"] == "阴性"
        assert item["current"]["n_nonevents"] == 500
        # ⌈9500/9⌉−500 = 1056−500 = 556
        assert item["gap"]["additional_minority_rows"] == 556

    def test_boundary_10pct_not_triggered(self) -> None:
        # 阳性率恰 10% 不触发(阈值严格小于)
        plan = advise_supplements(None, _eda(1000, 5, 100), [], _research())
        assert not any(i["deficit_type"] == "imbalance" for i in plan["items"])

    def test_dedup_when_epv_rule_fired(self) -> None:
        # 5000 例、40 特征、100 阳性:EPV=2.5 不足(①触发)且阳性率 2%<10%
        # → ① 已给出同一组补样数字,② 去重不再报
        plan = advise_supplements(None, _eda(5000, 40, 100), [], _research())
        assert any(i["deficit_type"] == "epv" for i in plan["items"])
        assert not any(i["deficit_type"] == "imbalance" for i in plan["items"])

    def test_balanced_not_triggered(self) -> None:
        plan = advise_supplements(None, _eda(10000, 20, 5000), [], _research())
        assert not any(i["deficit_type"] == "imbalance" for i in plan["items"])
