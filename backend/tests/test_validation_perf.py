"""T2.7 校验性能测试（docs/05 §6、docs/18 T2.7 DoD：10w 行 ≤30s）。

性能预算含：编码嗅探 + CSV 解析 + 列类型/语义推断 + 13 规则 + 列画像。
结果记录于提交信息（DoD「性能测试记录」）。
"""

import time

import numpy as np
import pandas as pd
from app.engines import parser, validation

_ROWS = 100_000
_BUDGET_SECONDS = 30.0


def _big_csv() -> bytes:
    rng = np.random.default_rng(42)
    df = pd.DataFrame(
        {
            "patient_id": [f"P{i:06d}" for i in range(_ROWS)],
            "age": rng.integers(18, 90, _ROWS),
            "gender": rng.choice(["男", "女"], _ROWS),
            "diagnosis": rng.choice(["高血压", "糖尿病", "冠心病", "肺炎"], _ROWS),
            "wbc": np.round(rng.normal(7.0, 2.0, _ROWS), 2),
            "血钾": np.round(rng.normal(4.2, 0.5, _ROWS), 2),
            "肌酐": np.round(rng.normal(80, 25, _ROWS), 1),
            "os_months": np.round(rng.uniform(1, 120, _ROWS), 1),
            "death": rng.integers(0, 2, _ROWS),
            "备注": rng.choice(["无", "复查", "随访中"], _ROWS),
        }
    )
    # 制造少量真实数据问题（缺失/异常），确保全规则路径执行
    df.loc[df.index[:25_000], "wbc"] = None  # 25% 缺失 → RV201 警告
    df.loc[df.index[100:200], "血钾"] = 0.2
    return df.to_csv(index=False).encode("utf-8")


class TestValidationPerformance:
    def test_100k_rows_within_budget(self) -> None:
        data = _big_csv()
        t0 = time.perf_counter()
        result = parser.parse_csv(data)
        report = validation.validate(result.df, raw_columns=result.raw_columns)
        elapsed = time.perf_counter() - t0

        assert result.df.shape == (_ROWS, 10)
        assert report.summary["rows"] == _ROWS
        #  sanity：规则确实执行了（缺失警告 + 血钾范围警告）
        rule_ids = {i.rule_id for i in report.issues}
        assert "RV201" in rule_ids and "RV502" in rule_ids
        assert elapsed <= _BUDGET_SECONDS, f"校验耗时 {elapsed:.1f}s 超过 30s 预算"
        print(f"\nPERF 10w 行解析+校验耗时: {elapsed:.2f}s")
