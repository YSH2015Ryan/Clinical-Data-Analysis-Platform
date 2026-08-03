"""P0-1 数据准备引擎单测（docs/05 §8）：长表+诊断表 → 宽表。

覆盖：词条归一/扫描、药敏剔除、winsorize、时间窗与防泄漏、取值策略、
结局判定范围、多标本后缀、TopN 截断、产出可通过 RV101。
"""

import pandas as pd
import pytest
from app.engines.preparation import PrepDecisions, prepare, scan
from app.engines.validation import validate


def _diag_df() -> pd.DataFrame:
    # P001：两次诊断（2020-01-01 炎症；2020-02-01 恶性肿瘤）；P002：炎症；P003：无词条命中
    return pd.DataFrame(
        {
            "患者ID": ["P001", "P001", "P002", "P003"],
            "诊断日期": ["2020-01-01", "2020-02-01", "2020-01-05", "2020-01-06"],
            "诊断": ["~炎症", "~恶性肿瘤;~癌", "~炎症;~上呼吸道感染", "~关节炎"],
            "年龄": [60, 60, 45, 70],
            "性别": ["男", "男", "女", "女"],
        }
    )


def _lab_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "患者ID": ["P001"] * 6 + ["P002"] * 3 + ["P004"] * 2,
            "诊断日期": ["2020-02-01"] * 6 + ["2020-01-05"] * 3 + ["2020-01-01"] * 2,
            "化验日期": [
                "2020-01-25",  # P001 葡萄糖 窗内（索引=首次 2020-01-01？见用例）
                "2020-01-28",  # P001 葡萄糖 更新一次
                "2020-01-10",  # P001 白细胞计数
                "2019-12-01",  # P001 白细胞计数 早于窗口（first 索引 2020-01-01，30 天窗）
                "2020-01-15",  # P001 万古霉素 药敏（异常=敏感）
                "2020-01-20",  # P001 葡萄糖_尿（多标本）
                "2020-01-03",  # P002 葡萄糖
                "2020-01-04",  # P002 白细胞计数
                "2020-03-01",  # P002 葡萄糖 晚于索引诊断（泄漏，应剔除）
                "2020-01-01",  # P004 葡萄糖（P004 无诊断记录）
                "2020-01-02",  # P004 极端值行
            ],
            "检验名称": [
                "葡萄糖",
                "葡萄糖",
                "白细胞计数",
                "白细胞计数",
                "万古霉素",
                "葡萄糖",
                "葡萄糖",
                "白细胞计数",
                "葡萄糖",
                "葡萄糖",
                "葡萄糖",
            ],
            "检验标本": ["血", "血", "血", "血", "血", "尿", "血", "血", "血", "血", "血"],
            "异常": [None] * 4 + ["敏感（S）"] + [None] * 6,
            "归一化值": [0.5, 0.7, 0.4, 0.3, None, 1.2, 0.6, 0.5, 0.9, 0.4, 55_805_580.0],
        }
    )


DEC = PrepDecisions(outcome_terms=("恶性肿瘤",), window_days=30)


class TestScan:
    def test_columns_and_terms(self) -> None:
        prev = scan(_lab_df(), _diag_df())
        assert prev.lab_columns["item"] == "检验名称"
        assert prev.lab_columns["value"] == "归一化值"
        assert prev.lab_columns["date"] == "化验日期"
        assert prev.diag_columns["text"] == "诊断"
        terms = {t["term"]: t["count"] for t in prev.diagnosis_terms}
        assert terms["炎症"] == 2  # ~ 前缀已归一
        assert terms["恶性肿瘤"] == 1
        assert prev.susceptibility_rows == 1
        assert prev.patients_intersection == 2  # P001/P002

    def test_suggested_defaults(self) -> None:
        prev = scan(_lab_df(), _diag_df())
        assert prev.suggested["value_column"] == "归一化值"
        assert prev.suggested["window_days"] == 30


class TestPrepare:
    def test_shape_and_label(self) -> None:
        res = prepare(_lab_df(), _diag_df(), DEC)
        wide = res.wide
        assert set(wide["患者ID"]) == {"P001", "P002", "P003"}
        label = dict(zip(wide["患者ID"], wide["label"], strict=True))
        assert label == {"P001": 1, "P002": 0, "P003": 0}

    def test_leakage_and_window(self) -> None:
        """诊断后化验剔除 + 窗口外剔除（docs/05 §8.2 D3/D4）。"""
        res = prepare(_lab_df(), _diag_df(), DEC)
        wide = res.wide.set_index("患者ID")
        # P002 的葡萄糖仅有 2020-01-03（窗内）与 2020-03-01（诊断后，剔除）
        assert wide.loc["P002", "葡萄糖_血"] == pytest.approx(0.6)
        # P001 索引=首次 2020-01-01：01-25/01-28 葡萄糖在诊断后 → 全部剔除
        assert pd.isna(wide.loc["P001", "葡萄糖_血"])

    def test_index_last_and_latest(self) -> None:
        d = PrepDecisions(outcome_terms=("恶性肿瘤",), index_diagnosis="last", window_days=60)
        res = prepare(_lab_df(), _diag_df(), d)
        wide = res.wide.set_index("患者ID")
        # 索引=末次 2020-02-01，latest → 取 01-28 的 0.7
        assert wide.loc["P001", "葡萄糖_血"] == pytest.approx(0.7)

    def test_mean_strategy(self) -> None:
        d = PrepDecisions(
            outcome_terms=("恶性肿瘤",),
            index_diagnosis="last",
            window_days=60,
            value_strategy="mean",
        )
        res = prepare(_lab_df(), _diag_df(), d)
        wide = res.wide.set_index("患者ID")
        assert wide.loc["P001", "葡萄糖_血"] == pytest.approx(0.6)  # (0.5+0.7)/2

    def test_susceptibility_excluded(self) -> None:
        res = prepare(_lab_df(), _diag_df(), DEC)
        assert not any("万古霉素" in c for c in res.wide.columns)
        assert res.summary["susceptibility_removed"] == 1

    def test_extreme_clipped(self) -> None:
        d = PrepDecisions(outcome_terms=("恶性肿瘤",), index_diagnosis="last", window_days=0)
        res = prepare(_lab_df(), _diag_df(), d)
        assert res.summary["clipped_rows"] >= 1
        # P004 无诊断记录 → 不在宽表（无索引诊断可锚定）
        assert "P004" not in set(res.wide["患者ID"])

    def test_outcome_scope_index(self) -> None:
        d = PrepDecisions(outcome_terms=("炎症",), outcome_scope="index", index_diagnosis="last")
        res = prepare(_lab_df(), _diag_df(), d)
        label = dict(zip(res.wide["患者ID"], res.wide["label"], strict=True))
        assert label["P001"] == 0  # 末次诊断是恶性肿瘤，炎症不在索引记录
        d2 = PrepDecisions(outcome_terms=("炎症",), outcome_scope="any")
        res2 = prepare(_lab_df(), _diag_df(), d2)
        label2 = dict(zip(res2.wide["患者ID"], res2.wide["label"], strict=True))
        assert label2["P001"] == 1

    def test_specimen_suffix(self) -> None:
        res = prepare(_lab_df(), _diag_df(), PrepDecisions(outcome_terms=("恶性肿瘤",)))
        cols = [c for c in res.wide.columns if c.startswith("葡萄糖")]
        assert sorted(cols) == ["葡萄糖_尿", "葡萄糖_血"]  # 葡萄糖跨标本 → 后缀
        assert "白细胞计数_血" not in res.wide.columns  # 单标本不加后缀

    def test_top_n_cap(self) -> None:
        d = PrepDecisions(outcome_terms=("恶性肿瘤",), top_n_items=1)
        res = prepare(_lab_df(), _diag_df(), d)
        feat = [c for c in res.wide.columns if c not in {"患者ID", "年龄", "性别", "label"}]
        assert len(feat) == 1

    def test_output_passes_rv101(self) -> None:
        """产出宽表可直接进入校验/分析（label 被识别为 Label 语义）。"""
        res = prepare(_lab_df(), _diag_df(), DEC)
        rep = validate(res.wide.drop(columns=["患者ID"]).rename(columns={"label": "label"}))
        assert [i for i in rep.issues if i.rule_id == "RV101"] == []

    def test_missing_column_raises_chinese(self) -> None:
        bad = _lab_df().drop(columns=["归一化值"])
        with pytest.raises(ValueError, match="归一化值"):
            prepare(bad, _diag_df(), DEC)
