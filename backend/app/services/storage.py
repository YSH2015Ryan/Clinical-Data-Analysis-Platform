"""存储抽象（docs/12 §2.4）：业务代码只依赖 StorageBackend 协议。

实现：LocalStorage（开发/单测）、S3Storage（MinIO/生产）。未来迁云零改动。
"""

import io
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from minio import Minio


@runtime_checkable
class StorageBackend(Protocol):
    def put(self, key: str, data: BinaryIO, length: int = -1) -> str: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def presign_download(self, key: str) -> str: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # 防路径穿越（docs/19 §7）：key 不允许含 ..
        if ".." in Path(key).parts:
            raise ValueError(f"非法存储 key: {key}")
        return self._root / key

    def put(self, key: str, data: BinaryIO, length: int = -1) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.read())
        return str(path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def presign_download(self, key: str) -> str:
        # 本地模式无预签名概念，返回文件路径（仅开发用）
        return str(self._path(key))


class S3Storage:
    def __init__(
        self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False
    ) -> None:
        host = endpoint.removeprefix("http://").removeprefix("https://")
        self._client = Minio(host, access_key=access_key, secret_key=secret_key, secure=secure)
        self._bucket = bucket
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    def put(self, key: str, data: BinaryIO, length: int = -1) -> str:
        payload = data.read()
        self._client.put_object(self._bucket, key, io.BytesIO(payload), len(payload))
        return f"s3://{self._bucket}/{key}"

    def get(self, key: str) -> bytes:
        resp = self._client.get_object(self._bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def exists(self, key: str) -> bool:
        try:
            self._client.stat_object(self._bucket, key)
            return True
        except Exception:
            return False

    def presign_download(self, key: str) -> str:
        return self._client.presigned_get_object(self._bucket, key)


def build_storage(
    backend: str,
    *,
    local_path: str = "./.data/storage",
    s3_endpoint: str = "",
    s3_access_key: str = "",
    s3_secret_key: str = "",
    s3_bucket: str = "cdap",
    s3_secure: bool = False,
) -> StorageBackend:
    if backend == "s3":
        return S3Storage(s3_endpoint, s3_access_key, s3_secret_key, s3_bucket, s3_secure)
    return LocalStorage(local_path)


def storage_from_settings() -> StorageBackend:
    from app.core.config import get_settings

    s = get_settings()
    return build_storage(
        s.storage_backend,
        local_path=s.local_storage_path,
        s3_endpoint=s.s3_endpoint,
        s3_access_key=s.s3_access_key,
        s3_secret_key=s.s3_secret_key,
        s3_bucket=s.s3_bucket,
        s3_secure=s.s3_secure,
    )


def key_from_uri(uri: str) -> str:
    """S3 uri (s3://bucket/key) → key；local 模式 uri 即路径，key 取 datasets/ 起的相对部分。"""
    if uri.startswith("s3://"):
        return uri.split("/", 3)[3]
    idx = uri.find("datasets/")
    return uri[idx:] if idx >= 0 else uri
