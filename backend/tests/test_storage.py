"""T0.5 DoD：存储抽象（LocalStorage 双实现一致性 + 路径穿越防护 + 预签名公网重写）。"""

import io

import pytest
from app.services.storage import LocalStorage, StorageBackend, _presign_client


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


class TestPresignClient:
    """预签名须按浏览器可达端点签名（docs/12 §2.4）：host 计入 SigV4 签名。

    显式 region 使预签名为纯本地计算——本测试在容器内执行，localhost:9000
    不可达，若触发服务端 region 探测会报错/超时，即为回归信号。
    """

    def test_signs_with_public_host(self) -> None:
        client = _presign_client("http://localhost:9000", "ak", "sk")
        url = client.presigned_get_object("cdap", "reports/abc/report.pdf")
        assert url.startswith("http://localhost:9000/cdap/reports/abc/report.pdf?")
        assert "X-Amz-Signature=" in url

    def test_https_public_endpoint(self) -> None:
        client = _presign_client("https://files.example.com", "ak", "sk")
        url = client.presigned_get_object("cdap", "runs/r1/model.pkl")
        assert url.startswith("https://files.example.com/cdap/runs/r1/model.pkl?")
