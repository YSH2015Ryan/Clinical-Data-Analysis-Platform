"""云端 LLM payload 红线守卫（T6.6 红线；CLAUDE.md 规范 8）。

任何情况下不向云端 LLM 发送行级患者数据：只允许聚合统计 facts 与列元数据。
在 cloud provider 入口强制校验 payload 结构——结构性启发式：
- 序列化体积上限（聚合 facts 通常 < 8KB）；
- 单个集合长度上限（fold 指标/分位网格等聚合数组 ≤200；行级数据随行数膨胀）；
- 禁用键名（rows/records/patients/raw_rows 等行级语义）。
"""

import json
from typing import Any

MAX_FACTS_BYTES = 8192
MAX_COLLECTION_LEN = 200
_FORBIDDEN_KEYS = {
    "rows",
    "records",
    "patients",
    "raw_rows",
    "row_data",
    "patient_level",
    "raw_data",
    "source_rows",
}


class CloudPayloadViolation(ValueError):
    """payload 含疑似行级数据，禁止发送云端。"""


def _walk(node: Any, path: str) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            key_str = str(key).lower()
            if key_str in _FORBIDDEN_KEYS:
                raise CloudPayloadViolation(f"payload 含禁用键 {path}.{key}（疑似行级数据）")
            _walk(value, f"{path}.{key}")
    elif isinstance(node, (list, tuple)):
        if len(node) > MAX_COLLECTION_LEN:
            raise CloudPayloadViolation(
                f"payload 集合 {path} 长度 {len(node)} 超过 {MAX_COLLECTION_LEN}（疑似行级数据）"
            )
        for i, item in enumerate(node):
            _walk(item, f"{path}[{i}]")


def assert_cloud_payload_safe(facts: dict[str, Any]) -> None:
    """云端发送前强制校验；违规抛 CloudPayloadViolation。"""
    try:
        blob = json.dumps(facts, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise CloudPayloadViolation(f"payload 不可 JSON 序列化：{exc}") from exc
    if len(blob.encode()) > MAX_FACTS_BYTES:
        raise CloudPayloadViolation(
            f"payload 体积 {len(blob.encode())}B 超过 {MAX_FACTS_BYTES}B（疑似行级数据）"
        )
    _walk(facts, "$")
