"""T3.5/T3.6 推荐配置端点测试：合法 200 + 隔离 404（docs/14 §3，契约变更 2026-07-30）。"""

import io

import pytest
from app.core.security import create_token, hash_password
from app.models.entities import Dataset, Project, User
from app.services.storage import storage_from_settings
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

CSV_BYTES = (
    "patient_id,age,gender,wbc,death\n"
    + "\n".join(
        f"P{i:03d},{20 + i},{'男' if i % 2 else '女'},{5.0 + i * 0.1},{i % 2}" for i in range(20)
    )
).encode("utf-8")


@pytest.fixture()
async def dataset(db_session: AsyncSession) -> tuple[Dataset, User]:
    user = User(
        email="rec@example.com",
        password_hash=hash_password("rec-pass"),
        role="researcher",
        display_name="REC",
    )
    db_session.add(user)
    await db_session.flush()
    proj = Project(owner_id=user.id, name="推荐项目", description="")
    db_session.add(proj)
    await db_session.flush()
    storage = storage_from_settings()
    ds = Dataset(
        project_id=proj.id,
        name="a.csv",
        source_type="csv",
        storage_uri="",
        file_hash="d" * 64,
        file_size=len(CSV_BYTES),
        status="VALIDATED",
    )
    db_session.add(ds)
    await db_session.flush()
    key = f"datasets/{proj.id}/{ds.id}/a.csv"
    ds.storage_uri = storage.put(key, io.BytesIO(CSV_BYTES), len(CSV_BYTES))
    # 端点要求校验已完成（column_profile 非空）：用真实校验结果填充
    from app.engines import parser, validation

    parsed = parser.parse(CSV_BYTES, "csv")
    ds.column_profile = validation.validate(parsed.df, raw_columns=parsed.raw_columns).column_profiles
    await db_session.commit()
    return ds, user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(str(user.id), user.role, 'access')}"}


class TestPreprocessRecommend:
    async def test_recommend_200(self, client: AsyncClient, dataset: tuple[Dataset, User]) -> None:
        ds, user = dataset
        resp = await client.post(
            f"/api/v1/datasets/{ds.id}/preprocess/recommend", headers=_auth(user)
        )
        assert resp.status_code == 200
        cfg = resp.json()["config"]
        assert cfg["validation"]["seed"] == 42
        assert cfg["target"].get("label_col") == "death"
        types = [s["type"] for s in cfg["steps"]]
        assert "drop_columns" in types and "missing" in types

    async def test_cross_owner_404(
        self, client: AsyncClient, db_session: AsyncSession, dataset: tuple[Dataset, User]
    ) -> None:
        ds, _ = dataset
        other = User(
            email="rec-o@example.com",
            password_hash=hash_password("o-pass"),
            role="researcher",
            display_name="O",
        )
        db_session.add(other)
        await db_session.commit()
        resp = await client.post(
            f"/api/v1/datasets/{ds.id}/preprocess/recommend", headers=_auth(other)
        )
        assert resp.status_code == 404


LONG_CSV = (
    "patient_id,item_name,value\n"
    + "\n".join(
        f"P{i:03d},{item},{10.0 + i + j}"
        for i in range(8)
        for j, item in enumerate(("wbc", "plt", "hgb"))
    )
).encode("utf-8")


class TestLongTableReshapeRecommend:
    """P1-2：校验判定为长表（RV801）时，推荐配置必须回退到 DataFrame 版
    以产出 reshape 步骤——profile 版无法做行级长表检测（双实现分叉修复）。"""

    async def test_reshape_recommended_for_long_table(
        self, client: AsyncClient, db_session: AsyncSession, dataset: tuple[Dataset, User]
    ) -> None:
        from app.models.entities import DatasetVersion, QualityReport

        ds, user = dataset
        # 换成长表文件 + 长表 profile + RV801 质量报告
        storage = storage_from_settings()
        ds.storage_uri = storage.put(
            f"datasets/{ds.project_id}/{ds.id}/long.csv", io.BytesIO(LONG_CSV), len(LONG_CSV)
        )
        from app.engines import parser, validation

        parsed = parser.parse(LONG_CSV, "csv")
        report = validation.validate(parsed.df, raw_columns=parsed.raw_columns)
        ds.column_profile = report.column_profiles
        version = DatasetVersion(
            dataset_id=ds.id, version_no=1, storage_uri=ds.storage_uri, transform_log=[]
        )
        db_session.add(version)
        await db_session.flush()
        assert any(i.rule_id == "RV801" for i in report.issues), "fixture 应触发 RV801"
        db_session.add(
            QualityReport(
                dataset_id=ds.id,
                dataset_version_id=version.id,
                status=report.status,
                blockers=report.blockers,
                warnings=report.warnings,
                issues=[i.to_dict() for i in report.issues],
                column_profiles=report.column_profiles,
            )
        )
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/datasets/{ds.id}/preprocess/recommend", headers=_auth(user)
        )
        assert resp.status_code == 200, resp.text
        cfg = resp.json()["config"]
        types = [s["type"] for s in cfg["steps"]]
        assert "reshape" in types, f"长表必须推荐 reshape，实际: {types}"
        reshape = cfg["steps"][types.index("reshape")]
        assert reshape["params"]["mode"] == "long_to_wide"
        assert reshape["params"]["index"] == "patient_id"

    async def test_wide_table_still_uses_fast_profile_path(
        self, client: AsyncClient, dataset: tuple[Dataset, User]
    ) -> None:
        ds, user = dataset
        resp = await client.post(
            f"/api/v1/datasets/{ds.id}/preprocess/recommend", headers=_auth(user)
        )
        assert resp.status_code == 200
        types = [s["type"] for s in resp.json()["config"]["steps"]]
        assert "reshape" not in types
