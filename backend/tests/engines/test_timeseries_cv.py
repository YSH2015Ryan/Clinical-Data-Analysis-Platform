"""Acceptance tests for chronological sliding-window cross-validation."""

from __future__ import annotations

import numpy as np
import pytest
from app.engines.timeseries_cv import iter_timeseries_cv_splits


def test_timeseries_cv_basic() -> None:
    splits = list(iter_timeseries_cv_splits(100, n_splits=3, test_size=20))
    assert np.array_equal(splits[0][0], np.arange(40))
    assert np.array_equal(splits[0][1], np.arange(40, 60))
    assert np.array_equal(splits[-1][0], np.arange(80))
    assert np.array_equal(splits[-1][1], np.arange(80, 100))


def test_timeseries_cv_train_size_grows() -> None:
    splits = list(iter_timeseries_cv_splits(50, n_splits=4, test_size=8))
    assert [len(train) for train, _ in splits] == [18, 26, 34, 42]


def test_timeseries_cv_test_size_fixed() -> None:
    splits = list(iter_timeseries_cv_splits(50, n_splits=4, test_size=8))
    assert all(len(test) == 8 for _, test in splits)


def test_timeseries_cv_chronological_order() -> None:
    splits = list(iter_timeseries_cv_splits(60, n_splits=5, test_size=7))
    test_sets = [set(test.tolist()) for _, test in splits]
    assert all(set(train).isdisjoint(test) for train, test in splits)
    assert all(train[-1] < test[0] for train, test in splits)
    assert all(np.all(np.diff(train) > 0) for train, _ in splits)
    assert all(np.all(np.diff(test) > 0) for _, test in splits)
    assert (
        sum(
            len(left & right)
            for i, left in enumerate(test_sets)
            for right in test_sets[i + 1 :]
        )
        == 0
    )


def test_timeseries_cv_n_splits() -> None:
    assert len(list(iter_timeseries_cv_splits(100, n_splits=7, test_size=10))) == 7


def test_timeseries_cv_edge_cases() -> None:
    splits = list(iter_timeseries_cv_splits(6, n_splits=2, test_size=2))
    assert [len(train) for train, _ in splits] == [2, 4]
    assert [len(test) for _, test in splits] == [2, 2]
    default_splits = list(iter_timeseries_cv_splits(10, n_splits=3))
    assert [len(test) for _, test in default_splits] == [2, 2, 2]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"n_samples": 0}, "n_samples"),
        ({"n_samples": 20, "n_splits": 1}, "n_splits"),
        ({"n_samples": 20, "n_splits": 3, "test_size": 0}, "test_size"),
        ({"n_samples": 20, "n_splits": 3, "test_size": 7}, "test_size"),
    ],
)
def test_timeseries_cv_invalid_params(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        iter_timeseries_cv_splits(**kwargs)


def test_timeseries_cv_return_format() -> None:
    indices = list(iter_timeseries_cv_splits(30, n_splits=3, test_size=5))
    assert all(isinstance(split, tuple) and len(split) == 2 for split in indices)
    assert all(isinstance(index, np.ndarray) for split in indices for index in split)
    X = np.arange(30)
    for train_idx, test_idx in indices:
        assert np.array_equal(X[train_idx], train_idx)
        assert np.array_equal(X[test_idx], test_idx)
