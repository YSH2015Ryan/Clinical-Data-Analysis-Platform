"""T0.3/T0.5 DoD：健康检查端点（docs/14）。"""

from app.main import create_app
from fastapi.testclient import TestClient


def test_healthz() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/v1/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_reports_components() -> None:
    # 无真实 PG/Redis 时应为 503，但结构必须符合契约
    client = TestClient(create_app())
    resp = client.get("/api/v1/readyz")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert "components" in body
    assert set(body["components"]) >= {"database", "redis"}
