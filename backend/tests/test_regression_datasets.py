"""§86 回归数据集骨架（Dataset A–J）冒烟测试：结构性质与已知问题锚定。

每个生成器须确定性地产出带「已知问题」的数据集；本测试只验证
骨架性质（不平衡率、重复数、泄漏列完美预测、EPV 等），问题检出
能力由对应引擎的测试覆盖（validation/leakage/supplement_advisor）。
"""

import numpy as np
from tests.fixtures import regression_datasets as rd


def test_dataset_a_normal_binary() -> None:
    df = rd.make_dataset_a()
    assert len(df) == 500
    assert set(df["outcome"].unique()) <= {0, 1}
    assert df["outcome"].mean() > 0.05  # 正常数据集不应极端不平衡


def test_dataset_b_severe_imbalance() -> None:
    df = rd.make_dataset_b()
    assert df["outcome"].mean() < 0.05  # 阳性率 ≈ 3.5%（§88 锚定）


def test_dataset_c_leakage_column_perfectly_predicts() -> None:
    df = rd.make_dataset_c()
    # month_group 由结局派生：分组即可完美预测结局（泄漏）
    assert (df.loc[df["month_group"] == "M9", "outcome"] == 1).all()
    assert (df.loc[df["month_group"] == "M1", "outcome"] == 0).all()


def test_dataset_d_contains_duplicates() -> None:
    df = rd.make_dataset_d()
    dup_rows = int(df.duplicated().sum())
    assert dup_rows >= 60  # 500 × 15% = 75 行整行重复


def test_dataset_e_extreme_outliers() -> None:
    df = rd.make_dataset_e()
    assert (df["age"] == 598.0).sum() == 5  # §88 锚定的 age=598


def test_dataset_f_temporal_structure() -> None:
    df = rd.make_dataset_f()
    assert "admission_date" in df.columns and "followup_month" in df.columns
    assert df["followup_month"].between(1, 12).all()


def test_dataset_g_survival_columns() -> None:
    df = rd.make_dataset_g()
    assert (df["time"] > 0).all()
    assert set(df["event"].unique()) <= {0, 1}
    assert 0.2 < df["event"].mean() < 1.0  # 既有事件又有删失


def test_dataset_h_scalable() -> None:
    df = rd.make_dataset_h()
    assert len(df) == 2000  # 骨架默认缩小；全量传 n=300_000


def test_dataset_i_is_ground_truth() -> None:
    df, truth = rd.make_dataset_i()
    assert truth["true_or"] == 2.0
    assert {"treatment", "age", "outcome"} <= set(df.columns)


def test_dataset_j_low_epv() -> None:
    df = rd.make_dataset_j()
    events = int(df["outcome"].sum())
    n_features = len([c for c in df.columns if c.startswith("x")])
    assert events == 40 and n_features == 20
    assert events / n_features == 2.0  # EPV=2，远低于经验阈值 10


def test_deterministic_generation() -> None:
    """同一生成器两次调用结果完全一致（CLAUDE.md 规范 6 种子纪律）。"""
    a1, a2 = rd.make_dataset_a(), rd.make_dataset_a()
    assert np.array_equal(a1.to_numpy(), a2.to_numpy())
