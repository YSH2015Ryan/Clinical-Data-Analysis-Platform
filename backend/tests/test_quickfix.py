"""T2.6 Quick Fix 引擎单测：4 动作（docs/05 §5）。"""

import pandas as pd
import pytest
from app.engines.quickfix import QuickFixAction, apply_actions


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "patient_id": ["P1", "P2", "P3", "P3"],
            "age": [55, 61, 47, 47],
            "alt": ["10", "未知", "30", "30"],
            "os_months": [12.0, 24.0, 8.0, 8.0],
            "death": [1, 0, 1, 1],
        }
    )


class TestDropColumn:
    def test_positive(self) -> None:
        new_df, log = apply_actions(_df(), [QuickFixAction(type="drop_column", column="alt")])
        assert "alt" not in new_df.columns
        assert log[0]["action"] == "drop_column"
        assert log[0]["column"] == "alt"

    def test_missing_column_raises(self) -> None:
        with pytest.raises(ValueError, match="不存在"):
            apply_actions(_df(), [QuickFixAction(type="drop_column", column="nope")])


class TestDropDuplicates:
    def test_positive(self) -> None:
        new_df, log = apply_actions(_df(), [QuickFixAction(type="drop_duplicates")])
        assert len(new_df) == 3
        assert log[0]["affected_rows"] == 1

    def test_no_duplicates(self) -> None:
        new_df, log = apply_actions(
            _df().drop_duplicates(), [QuickFixAction(type="drop_duplicates")]
        )
        assert len(new_df) == 3
        assert log[0]["affected_rows"] == 0


class TestToMissing:
    def test_non_numeric_to_nan(self) -> None:
        new_df, log = apply_actions(_df(), [QuickFixAction(type="to_missing", column="alt")])
        assert log[0]["affected_rows"] == 1
        assert new_df["alt"].isna().sum() == 1
        assert new_df["alt"].dropna().tolist() == [10.0, 30.0, 30.0]

    def test_explicit_values(self) -> None:
        df = _df()
        df["备注"] = ["好", "不详", "好", "不详"]
        new_df, log = apply_actions(
            df,
            [QuickFixAction(type="to_missing", column="备注", params={"values": ["不详"]})],
        )
        assert log[0]["affected_rows"] == 2
        assert new_df["备注"].isna().sum() == 2


class TestRemapSemantic:
    def test_positive(self) -> None:
        new_df, log = apply_actions(
            _df(),
            [
                QuickFixAction(
                    type="remap_semantic", column="os_months", params={"semantic": "FollowUp"}
                )
            ],
        )
        assert new_df.equals(_df())  # 不改数据
        assert log[0]["params"]["semantic"] == "FollowUp"

    def test_invalid_semantic_raises(self) -> None:
        with pytest.raises(ValueError, match="语义"):
            apply_actions(
                _df(),
                [
                    QuickFixAction(
                        type="remap_semantic", column="os_months", params={"semantic": "Foo"}
                    )
                ],
            )


class TestGuards:
    def test_unknown_action_raises(self) -> None:
        with pytest.raises(ValueError, match="未知修复动作"):
            apply_actions(_df(), [QuickFixAction(type="explode")])

    def test_actions_chain(self) -> None:
        new_df, log = apply_actions(
            _df(),
            [
                QuickFixAction(type="to_missing", column="alt"),
                QuickFixAction(type="drop_duplicates"),
                QuickFixAction(type="drop_column", column="alt"),
            ],
        )
        assert "alt" not in new_df.columns
        assert len(log) == 3
