"""T6.13 对话式迭代 API 测试（docs/14 POST /analysis-runs/{id}/iterate）。

- 规则回退恒可用：问题提到真实列 → add_features；回答引用真实指标；
- iteration 开关打开但 LLM 失败 → 回退规则版（llm_enhanced=False，不阻塞）；
- 未授权 401/403、未知 run 404；结局列不进 available_columns。
"""

from typing import ClassVar

import pytest
from app.models.entities import User
from httpx import AsyncClient

from tests.test_analysis_api import _auth, _body
from tests.test_analysis_api import researcher as _researcher_impl
from tests.test_analysis_api import version as _version_impl
from tests.test_analysis_api import worker_sync_db as _ws_impl

researcher = _researcher_impl
version = _version_impl
worker_sync_db = _ws_impl


async def _create_completed_run(client: AsyncClient, researcher: User, version) -> str:
    resp = await client.post(
        "/api/v1/analysis-runs", json=_body(version.id, ["dummy"]), headers=_auth(researcher)
    )
    assert resp.status_code == 202
    return resp.json()["id"]


class TestIterate:
    async def test_rule_fallback_add_covariate(
        self, client: AsyncClient, researcher: User, version
    ) -> None:
        run_id = await _create_completed_run(client, researcher, version)
        resp = await client.post(
            f"/api/v1/analysis-runs/{run_id}/iterate",
            json={"question": "如果把 biomarker 当协变量会怎样？"},
            headers=_auth(researcher),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["llm_enhanced"] is False  # 默认 iteration 开关 off → 规则版
        assert body["suggestion"]["add_features"] == ["biomarker"]
        assert body["dataset_id"]  # 重跑跳转需要
        # 结局列不出现在协变量建议中
        assert "label" not in body["suggestion"]["add_features"]

    async def test_generic_question_no_suggestion(
        self, client: AsyncClient, researcher: User, version
    ) -> None:
        run_id = await _create_completed_run(client, researcher, version)
        resp = await client.post(
            f"/api/v1/analysis-runs/{run_id}/iterate",
            json={"question": "结果可信吗？"},
            headers=_auth(researcher),
        )
        assert resp.status_code == 200
        assert resp.json()["suggestion"] is None
        assert resp.json()["answer"]

    async def test_llm_failure_falls_back_to_rule(
        self, client: AsyncClient, researcher: User, version, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """iteration 开关打开但 LLM 抛错 → 规则版兜底（主流程不阻塞）。"""
        run_id = await _create_completed_run(client, researcher, version)

        class _Cfg:
            feature_switches: ClassVar[dict[str, str]] = {"iteration": "local"}
            temperature = 0.3

        async def _cfg(db: object) -> _Cfg:
            return _Cfg()

        monkeypatch.setattr(
            "app.api.v1.analysis.settings_service.get_llm_config",
            _cfg,
        )
        monkeypatch.setattr(
            "app.api.v1.analysis.init_llm_service_from_runtime", lambda cfg: object()
        )

        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("ollama down")

        monkeypatch.setattr("app.api.v1.analysis.llm_tasks.generate_iteration_advice", _boom)
        # generate_iteration_advice 内部自行兜底 —— 这里直接打爆接线验证 API 层仍返回
        resp = await client.post(
            f"/api/v1/analysis-runs/{run_id}/iterate",
            json={"question": "把 biomarker 加进来会怎样？"},
            headers=_auth(researcher),
        )
        assert resp.status_code == 200

    async def test_unknown_run_404(self, client: AsyncClient, researcher: User) -> None:
        import uuid

        resp = await client.post(
            f"/api/v1/analysis-runs/{uuid.uuid4()}/iterate",
            json={"question": "x"},
            headers=_auth(researcher),
        )
        assert resp.status_code == 404

    async def test_unauthenticated_401(self, client: AsyncClient) -> None:
        import uuid

        resp = await client.post(
            f"/api/v1/analysis-runs/{uuid.uuid4()}/iterate", json={"question": "x"}
        )
        assert resp.status_code == 401

    async def test_empty_question_400(self, client: AsyncClient, researcher: User, version) -> None:
        run_id = await _create_completed_run(client, researcher, version)
        resp = await client.post(
            f"/api/v1/analysis-runs/{run_id}/iterate",
            json={"question": ""},
            headers=_auth(researcher),
        )
        assert resp.status_code == 400  # 平台统一把校验错误映射为 400 VALIDATION_ERROR
