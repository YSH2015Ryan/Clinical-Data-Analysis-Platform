"""T6.14 数据缺口建议引擎测试（路线图 T6.14；红线 8 数值全部真实计算）。

判断/计算全部确定性规则；每条建议附 basis 依据串（含真实数值与公式），
可展开核对。① EPV 不足：缺口事件=⌈10×特征数−阳性数⌉，需补样本量=
⌈缺口事件/阳性率⌉；阳性率=0 时不出 N（那是编造），改提示确认结局定义。
"""

from typing import Any

import pandas as pd
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


def _cohort_df(n_rows: int, n_events: int) -> pd.DataFrame:
    """合成队列数据:followup_days(1..n)数值随访列 + death 0/1 事件列。"""
    events = [1] * n_events + [0] * (n_rows - n_events)
    return pd.DataFrame({"followup_days": list(range(1, n_rows + 1)), "death": events})


class TestSurvivalEvents:
    """③ 生存事件不足:队列研究(有随访时间列+0/1 事件列)且事件数<100。

    阈值 100 为本规则经验下限(依据串明示,非外部金标准);缺口=100−事件数;
    建议引用真实中位随访时间。无随访/事件列或非队列研究不误报。
    """

    def test_survival_deficit_real_numbers(self) -> None:
        # 120 例、35 事件 → 缺口 65;中位随访=(60+61)/2=60.5
        df = _cohort_df(120, 35)
        plan = advise_supplements(df, _eda(120, 8, 35), [], _research("cohort"))
        item = next(i for i in plan["items"] if i["deficit_type"] == "survival_events")
        assert item["current"]["n_events"] == 35
        assert item["current"]["event_column"] == "death"
        assert item["current"]["follow_up_median"] == 60.5
        assert item["gap"]["missing_events"] == 65
        assert "35" in item["basis"] and "65" in item["basis"]
        assert "60.5" in item["suggestion"] and "随访" in item["suggestion"]

    def test_boundary_100_events_not_triggered(self) -> None:
        df = _cohort_df(300, 100)
        plan = advise_supplements(df, _eda(300, 8, 100), [], _research("cohort"))
        assert not any(i["deficit_type"] == "survival_events" for i in plan["items"])

    def test_non_cohort_not_triggered(self) -> None:
        # 结构相同但研究画像为横断面 → 以画像为准,不报生存缺口
        df = _cohort_df(120, 35)
        plan = advise_supplements(df, _eda(120, 8, 35), [], _research("cross_sectional"))
        assert not any(i["deficit_type"] == "survival_events" for i in plan["items"])

    def test_cohort_without_survival_columns_not_triggered(self) -> None:
        # 队列画像但无随访时间/事件列 → 无法判定,不误报
        df = pd.DataFrame({"age": [50, 60], "bmi": [22.0, 25.0]})
        plan = advise_supplements(df, _eda(2, 2, None), [], _research("cohort"))
        assert not any(i["deficit_type"] == "survival_events" for i in plan["items"])

    def test_no_df_not_triggered(self) -> None:
        plan = advise_supplements(None, _eda(120, 8, 35), [], _research("cohort"))
        assert not any(i["deficit_type"] == "survival_events" for i in plan["items"])


class TestVariableRoles:
    """④ 变量角色缺失:按研究类型核对必备角色,只提示角色不猜数值。

    队列=随访时间+事件(结局)+年龄+性别;病例对照=分组+年龄+性别;
    横断面=年龄+性别;时序不适用。检出列名写进 basis(真实),缺失角色进 gap。
    """

    def test_cohort_missing_followup_and_event(self) -> None:
        # 队列只有年龄/性别 → 缺随访时间与事件角色
        df = pd.DataFrame({"age": [50, 60], "sex": ["M", "F"]})
        plan = advise_supplements(df, _eda(2, 2, None), [], _research("cohort"))
        item = next(i for i in plan["items"] if i["deficit_type"] == "variable_roles")
        assert item["gap"]["missing_roles"] == ["随访时间", "事件(结局)"]
        assert item["current"]["detected"]["年龄"] == "age"
        assert item["current"]["detected"]["性别"] == "sex"
        assert "随访" in item["suggestion"]
        assert "age" in item["basis"]  # 依据串含真实检出列名

    def test_cross_sectional_missing_sex(self) -> None:
        df = pd.DataFrame({"age": [50, 60], "bmi": [22.0, 25.0]})
        plan = advise_supplements(df, _eda(2, 2, None), [], _research())
        item = next(i for i in plan["items"] if i["deficit_type"] == "variable_roles")
        assert item["gap"]["missing_roles"] == ["性别"]

    def test_cohort_all_roles_present_not_triggered(self) -> None:
        df = pd.DataFrame(
            {
                "followup_days": [100, 200, 300],
                "death": [0, 1, 0],
                "age": [50, 60, 70],
                "sex": ["M", "F", "M"],
            }
        )
        plan = advise_supplements(df, _eda(3, 4, 1), [], _research("cohort"))
        assert not any(i["deficit_type"] == "variable_roles" for i in plan["items"])

    def test_time_series_not_applicable(self) -> None:
        df = pd.DataFrame({"date": ["2026-01-01"], "value": [1.0]})
        plan = advise_supplements(df, _eda(1, 2, None), [], _research("time_series"))
        assert not any(i["deficit_type"] == "variable_roles" for i in plan["items"])

    def test_profiles_only_fallback(self) -> None:
        # 无 df 时退化为按 column_profiles 的列名判定
        profiles = [{"name": "age"}, {"name": "bmi"}]
        plan = advise_supplements(None, _eda(100, 2, None), profiles, _research())
        item = next(i for i in plan["items"] if i["deficit_type"] == "variable_roles")
        assert item["gap"]["missing_roles"] == ["性别"]

    def test_no_columns_info_not_triggered(self) -> None:
        # 既无 df 又无 profiles → 无法判定,不误报
        plan = advise_supplements(None, _eda(100, 2, None), [], _research())
        assert not any(i["deficit_type"] == "variable_roles" for i in plan["items"])


class TestGroupPower:
    """⑤ 组间比较把握度(B 方案):检出二分类分组列时,用真实组样本量计算
    两独立样本 t 检验在 d=0.2/0.5/0.8 三档效应量下的 power(α=0.05 双侧),
    并反解小效应(d=0.2)达 80% power 所需每组样本量;假设在依据串全部明示。
    中效应 power≥0.8 视为充足不报;无分组列/非二分类/无 df 不报。

    参考值(statsmodels TTestIndPower):n1=n2=30 → power=0.1187/0.4779/0.8614,
    反解 n≈393.4 → ⌈⌉=394 例/组。
    """

    def test_power_real_numbers_three_tiers(self) -> None:
        df = pd.DataFrame({"group": ["A"] * 30 + ["B"] * 30, "value": range(60)})
        plan = advise_supplements(df, _eda(60, 2, None), [], _research("case_control"))
        item = next(i for i in plan["items"] if i["deficit_type"] == "power")
        assert item["current"]["group_column"] == "group"
        assert item["current"]["n1"] == 30 and item["current"]["n2"] == 30
        tiers = item["gap"]["power_at_d"]
        assert tiers["0.2"] == 0.1187 and tiers["0.5"] == 0.4779
        assert tiers["0.8"] == 0.8614
        assert item["gap"]["n_per_group_for_small_effect"] == 394
        assert "394" in item["basis"] and "d=0.2" in item["basis"]
        assert "假设" in item["basis"]  # 假设明示

    def test_adequate_power_not_triggered(self) -> None:
        # 500/500:中效应 power=1.0 ≥0.8 → 充足不报
        df = pd.DataFrame({"group": ["A"] * 500 + ["B"] * 500, "value": range(1000)})
        plan = advise_supplements(df, _eda(1000, 2, None), [], _research("case_control"))
        assert not any(i["deficit_type"] == "power" for i in plan["items"])

    def test_no_group_column_not_triggered(self) -> None:
        df = pd.DataFrame({"age": [50, 60], "bmi": [22.0, 25.0]})
        plan = advise_supplements(df, _eda(2, 2, None), [], _research())
        assert not any(i["deficit_type"] == "power" for i in plan["items"])

    def test_three_level_group_not_triggered(self) -> None:
        # 三分类分组列:t 检验把握度不适用,不出数字(不编造)
        df = pd.DataFrame({"group": ["A"] * 20 + ["B"] * 20 + ["C"] * 20, "value": range(60)})
        plan = advise_supplements(df, _eda(60, 2, None), [], _research("case_control"))
        assert not any(i["deficit_type"] == "power" for i in plan["items"])

    def test_no_df_not_triggered(self) -> None:
        plan = advise_supplements(None, _eda(60, 2, None), [], _research("case_control"))
        assert not any(i["deficit_type"] == "power" for i in plan["items"])
