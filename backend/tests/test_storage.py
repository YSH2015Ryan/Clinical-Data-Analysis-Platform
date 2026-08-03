"""T0.5 DoD：存储抽象（LocalStorage 双实现一致性 + 路径穿越防护 + 预签名公网重写）。"""

import io

import pytest
from app.services.storage import LocalStorage, StorageBackend, _public_url


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


class TestPublicUrl:
    """预签名 host 重写（docs/12 §2.4）：浏览器不可达容器内域名 minio:9000。"""

    def test_rewrites_scheme_and_host_keeps_path_query(self) -> None:
        url = "http://minio:9000/cdap/reports/abc/report.pdf?X-Amz-Signature=deadbeef&X-Amz-Expires=604800"
        out = _public_url(url, "http://localhost:9000")
        assert out == (
            "http://localhost:9000/cdap/reports/abc/report.pdf"
            "?X-Amz-Signature=deadbeef&X-Amz-Expires=604800"
        )

    def test_https_public_endpoint(self) -> None:
        url = "http://minio:9000/cdap/runs/r1/model.pkl?X-Amz-Signature=x"
        out = _public_url(url, "https://files.example.com")
        assert out.startswith("https://files.example.com/cdap/runs/r1/model.pkl?")

    def test_empty_endpoint_passthrough(self) -> None:
        url = "http://minio:9000/cdap/a?sig=1"
        assert _public_url(url, "") == url
