"""T2.2 解析引擎单测：编码/分隔符/表头嗅探 + 预览 JSON（docs/05 §2、docs/19）。"""

import io
import json

import numpy as np
import pandas as pd
import pytest
from app.engines.parser import (
    detect_delimiter,
    detect_encoding,
    parse_csv,
    parse_excel,
    preview_json,
    normalize_json_value,
)

TEXT = "id,姓名,年龄\n1,张三,55\n2,李四,61\n"


class TestEncoding:
    def test_utf8(self) -> None:
        result = parse_csv(TEXT.encode("utf-8"))
        assert result.encoding == "utf-8"
        assert list(result.df.columns) == ["id", "姓名", "年龄"]
        assert result.df.iloc[0]["姓名"] == "张三"

    def test_utf8_bom(self) -> None:
        result = parse_csv(TEXT.encode("utf-8-sig"))
        assert list(result.df.columns) == ["id", "姓名", "年龄"]

    def test_gbk(self) -> None:
        data = TEXT.encode("gbk")
        result = parse_csv(data)
        assert result.encoding in {"gb18030", "gbk", "gb2312"}
        assert result.df.iloc[1]["姓名"] == "李四"

    def test_gb18030(self) -> None:
        data = TEXT.encode("gb18030")
        result = parse_csv(data)
        assert result.df.iloc[0]["姓名"] == "张三"

    def test_latin1_fallback(self) -> None:
        assert detect_encoding(b"plain ascii text") in {"ascii", "utf-8"}


class TestDelimiter:
    @pytest.mark.parametrize("delim", [",", ";", "\t", "|"])
    def test_sniff(self, delim: str) -> None:
        text = delim.join(["a", "b", "c"]) + "\n" + delim.join(["1", "2", "3"])
        assert detect_delimiter(text) == delim

    def test_semicolon_parse(self) -> None:
        result = parse_csv(b"a;b\n1;2\n3;4\n")
        assert result.delimiter == ";"
        assert result.df.shape == (2, 2)

    def test_raw_columns_preserve_duplicates(self) -> None:
        # pandas 会把重复列名改写为 a/a.1；raw_columns 保留原始表头供 RV003 判定
        result = parse_csv("年龄,年龄,death\n55,56,1\n".encode())
        assert result.raw_columns == ["年龄", "年龄", "death"]
        assert list(result.df.columns) == ["年龄", "年龄.1", "death"]


class TestExcel:
    def test_xlsx_roundtrip(self) -> None:
        buf = io.BytesIO()
        pd.DataFrame({"id": [1, 2], "姓名": ["张三", "李四"]}).to_excel(buf, index=False)
        result = parse_excel(buf.getvalue())
        assert result.df.shape == (2, 2)
        assert result.df.iloc[0]["姓名"] == "张三"


class TestPreview:
    def test_preview_caps_at_100_rows(self) -> None:
        df = pd.DataFrame({"x": range(500)})
        preview = preview_json(df)
        assert len(preview["rows"]) == 100
        assert preview["total_rows"] == 500
        assert preview["columns"] == ["x"]

    def test_nan_becomes_none(self) -> None:
        df = pd.DataFrame({"a": [1.0, None], "b": ["x", None]})
        preview = preview_json(df)
        assert preview["rows"][1] == [None, None]

    def test_json_serializable(self) -> None:
        df = pd.DataFrame({"a": [1, 2], "b": [1.5, None], "c": ["x", "y"]})
        json.dumps(preview_json(df))  # 不抛异常即通过


class TestNormalizeJsonValue:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (pd.Timestamp("2024-01-02T03:04:05"), "2024-01-02T03:04:05"),
            (pd.NaT, None),
            (pd.NA, None),
            (np.int64(7), 7),
            (np.array([1, np.nan], dtype=np.float64), [1.0, None]),
        ],
    )
    def test_json_serializable_values(self, value: object, expected: object) -> None:
        normalized = normalize_json_value(value)
        json.dumps(normalized)
        assert normalized == expected

    def test_nested_values_and_unsupported_leaves_are_json_safe(self) -> None:
        value = {
            pd.Timestamp("2024-01-02"): {
                "nat": pd.NaT,
                "na": pd.NA,
                "array": np.array([np.int64(1), np.nan]),
                "unsupported": object(),
            }
        }

        normalized = normalize_json_value(value)
        json.dumps(normalized)
        nested = normalized["2024-01-02T00:00:00"]
        assert nested["nat"] is None
        assert nested["na"] is None
        assert nested["array"] == [1, None]
        assert isinstance(nested["unsupported"], str)
