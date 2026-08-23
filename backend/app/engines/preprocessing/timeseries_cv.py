"""Chronological sliding-window cross-validation utilities.

The iterator yields positional indices suitable for pandas ``iloc`` and the
scikit-learn model-selection API.  Every training window contains only
observations strictly earlier than its test window; test windows are fixed in
size and never overlap.
"""

from __future__ import annotations

from typing import Any, Iterator

import numpy as np


def iter_timeseries_cv_splits(
    n_samples: int,
    n_splits: int = 5,
    test_size: int | None = None,
) -> Iterator[tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]]:
    """Yield chronological train/test positional-index pairs.

    The initial training window is ``n_samples - n_splits * test_size`` rows.
    Each subsequent split appends one test window to the training data while
    keeping the test window size fixed.  When ``test_size`` is omitted, it is
    chosen as ``n_samples // (n_splits + 1)`` so all observations are used.

    Examples
    --------
    >>> splits = list(iter_timeseries_cv_splits(10, n_splits=3, test_size=2))
    >>> [(train.tolist(), test.tolist()) for train, test in splits]
    [([0, 1, 2, 3], [4, 5]), ([0, 1, 2, 3, 4, 5], [6, 7]), ([0, 1, 2, 3, 4, 5, 6, 7], [8, 9])]

    Parameters
    ----------
    n_samples:
        Number of ordered observations.
    n_splits:
        Number of validation windows.  At least two are required, matching
        scikit-learn's ``TimeSeriesSplit`` convention.
    test_size:
        Number of observations in each test window.  The value must leave at
        least one training observation in the first split.

    Raises
    ------
    ValueError
        If a parameter is not a positive integer or the requested windows do
        not fit in the data.
    """

    if isinstance(n_samples, bool) or not isinstance(n_samples, (int, np.integer)):
        raise ValueError("n_samples must be an integer")
    if n_samples <= 0:
        raise ValueError("n_samples must be greater than zero")
    if isinstance(n_splits, bool) or not isinstance(n_splits, (int, np.integer)):
        raise ValueError("n_splits must be an integer")
    if n_splits < 2:
        raise ValueError("n_splits must be at least 2")
    if test_size is not None and (
        isinstance(test_size, bool) or not isinstance(test_size, (int, np.integer))
    ):
        raise ValueError("test_size must be an integer")

    resolved_test_size = (
        int(test_size) if test_size is not None else int(n_samples) // (int(n_splits) + 1)
    )
    if resolved_test_size <= 0:
        raise ValueError("test_size must be greater than zero")
    initial_train_size = int(n_samples) - int(n_splits) * resolved_test_size
    if initial_train_size < 1:
        raise ValueError(
            "test_size is too large for n_samples and n_splits; "
            "at least one training observation is required"
        )

    def _splits() -> Iterator[tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]]:
        for split_number in range(int(n_splits)):
            train_end = initial_train_size + split_number * resolved_test_size
            test_start = train_end
            test_end = test_start + resolved_test_size
            # The bounds are validated above; these slices cannot overlap and
            # preserve the original temporal ordering.
            yield (
                np.arange(0, train_end, dtype=int),
                np.arange(test_start, test_end, dtype=int),
            )

    return _splits()
