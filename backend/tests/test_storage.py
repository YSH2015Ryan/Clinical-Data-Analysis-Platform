"""T0.5 DoD：存储抽象（LocalStorage 双实现一致性 + 路径穿越防护）。"""

import io

import pytest
from app.services.storage import LocalStorage, StorageBackend


def test_local_storage_protocol_compliance(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage: StorageBackend = LocalStorage(str(tmp_path))
    assert isinstance(storage, StorageBackend)  # runtime_checkable 协议


def test_put_get_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = LocalStorage(str(tmp_path))
    storage.put("a/b/test.csv", io.BytesIO(b"x,y\n1,2\n"))
    assert storage.exists("a/b/test.csv")
    assert storage.get("a/b/test.csv") == b"x,y\n1,2\n"


def test_path_traversal_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    storage = LocalStorage(str(tmp_path))
    with pytest.raises(ValueError, match="非法存储 key"):
        storage.put("../escape.txt", io.BytesIO(b"x"))
