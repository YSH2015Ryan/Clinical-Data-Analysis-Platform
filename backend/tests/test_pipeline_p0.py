"""P0 validation split tests."""

import numpy as np
import pandas as pd

from app.engines.pipeline import iter_cv_splits
from app.engines.preprocessing import ValidationSpec


def test_group_split_never_separates_patient() -> None:
    df = pd.DataFrame({"patient_id": [1, 1, 2, 2, 3, 3, 4, 4], "x": range(8)})
    spec = ValidationSpec(strategy="stratified_group_kfold", n_splits=2, group_col="patient_id")
    folds = list(iter_cv_splits(df, spec, pd.Series([0, 1, 0, 1, 0, 1, 0, 1])))
    assert len(folds) == 2
    for train, valid in folds:
        assert set(df.iloc[train].patient_id).isdisjoint(set(df.iloc[valid].patient_id))


def test_time_split_is_forward_only() -> None:
    df = pd.DataFrame({"observed_at": pd.date_range("2024-01-01", periods=8), "x": range(8)})
    spec = ValidationSpec(strategy="time_series_split", n_splits=3, time_col="observed_at")
    for train, valid in iter_cv_splits(df, spec, None):
        assert np.max(df.index.to_numpy()[train]) < np.min(df.index.to_numpy()[valid])
