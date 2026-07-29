"""解析引擎（docs/05 §2）：编码/分隔符/表头嗅探 → DataFrame → 预览 JSON。

分层纪律：engines 只依赖数据处理库，禁止 import fastapi/celery/sqlalchemy。
"""

import csv
import io
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from charset_normalizer import from_bytes

_CANDIDATE_ENCODINGS = ("gb18030", "big5", "latin-1")
_DELIMITERS = ",;\t|"
_PREVIEW_ROWS = 100


@dataclass
class ParseResult:
    df: pd.DataFrame
    encoding: str | None  # excel 为 None
    delimiter: str | None  # excel 为 None
    raw_columns: list[str] | None = None  # 原始表头（RV003 重复列名判定；pandas 会改写重名）
    warnings: list[str] = field(default_factory=list)


def detect_encoding(data: bytes) -> str:
    """UTF-8 严格优先（避免 cp949 等小样本误判），非 UTF-8 走限定候选的嗅探。

    平台面向中文临床数据：候选限定 gb18030（gbk/gb2312 超集）/big5/latin-1，
    防止 charset-normalizer 将短 GBK 样本误判为韩文 cp949。
    """
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    best = from_bytes(data, cp_isolation=list(_CANDIDATE_ENCODINGS)).best()
    if best is not None and best.encoding:
        enc = best.encoding.lower().replace("_", "-")
        if enc in {"gb2312", "gbk"}:
            return "gb18030"
        return enc
    return "gb18030"  # 中文数据兜底（gbk/gb2312 超集）


def detect_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=_DELIMITERS).delimiter
    except csv.Error:
        # 单列文件（无分隔符）Sniffer 会失败
        return ","


def has_header(sample: str, delimiter: str) -> bool:
    try:
        return csv.Sniffer().has_header(sample)
    except csv.Error:
        return True


def _raw_header(text: str, delimiter: str) -> list[str] | None:
    """第一行按 csv 语义切分（含引号处理），供 RV003 重复列名判定。"""
    first_line = text.split("\n", 1)[0]
    try:
        return next(csv.reader([first_line], delimiter=delimiter))
    except StopIteration:
        return None


def parse_csv(data: bytes) -> ParseResult:
    encoding = detect_encoding(data)
    text = data.decode(encoding, errors="replace")
    sample = text[:8192]
    delimiter = detect_delimiter(sample)
    header = 0 if has_header(sample, delimiter) else None
    df = pd.read_csv(io.StringIO(text), sep=delimiter, header=header)
    raw_columns = _raw_header(text, delimiter) if header == 0 else None
    return ParseResult(df=df, encoding=encoding, delimiter=delimiter, raw_columns=raw_columns)


def parse_excel(data: bytes) -> ParseResult:
    df = pd.read_excel(io.BytesIO(data))
    header_row = pd.read_excel(io.BytesIO(data), header=None, nrows=1)
    raw_columns = [str(c) for c in header_row.iloc[0].tolist()] if len(header_row) else None
    return ParseResult(df=df, encoding=None, delimiter=None, raw_columns=raw_columns)


def parse(data: bytes, source_type: str) -> ParseResult:
    if source_type == "excel":
        return parse_excel(data)
    return parse_csv(data)


def preview_json(df: pd.DataFrame, n: int = _PREVIEW_ROWS) -> dict[str, Any]:
    """前 n 行预览：NaN/NaT → None，numpy 标量 → 原生类型（JSON 可序列化）。"""
    head = df.head(n)
    rows = [
        [None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in row]
        for row in head.itertuples(index=False, name=None)
    ]
    return {
        "columns": [str(c) for c in head.columns],
        "rows": rows,
        "total_rows": len(df),
    }
