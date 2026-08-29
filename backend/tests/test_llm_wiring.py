"""T6.7 LLM 接线三处业务（roadmap T6.7）。

- 分功能开关门控：off 一律跳过 LLM，规则/模板结果兜底，主流程不阻塞；
- 研究画像：LLM 输出 JSON 解析 + 模型/图表白名单 + 幻觉数值拦截；
- 报告解读：逐章节独立失败隔离，citable_numbers 纳入合法数值域；
- 校验解释：仅 blocker、限量、长度与幻觉校验；
- worker/API 接线：开关读 DB 运行层配置，失败回退。
"""

import json
import os
from typing import Any, ClassVar

import pytest
from app.models.entities import AdminSetting
from app.services import llm_tasks
from app.services.llm_tasks import (
    explain_validation_issues,
    generate_report_interpretations,
    generate_research_questions,
    switch_to_choice,
)
from app.workers import dataset_tasks, report_tasks
from app.workers import db as worker_db
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


class _StubService:
    """LLMService 替身：记录调用并按剧本返回/抛错。"""

    def __init__(
        self,
        complete_result: str | None = None,
        complete_exc: Exception | None = None,
        interp_results: dict[str, str] | None = None,
        interp_fail: set[str] | None = None,
    ) -> None:
        self.complete_result = complete_result
        self.complete_exc = complete_exc
        self.interp_results = interp_results or {}
        self.interp_fail = interp_fail or set()
        self.complete_calls: list[dict[str, Any]] = []
        self.interp_calls: list[dict[str, Any]] = []

    def complete(self, prompt: str, **kwargs: Any) -> str:
        self.complete_calls.append({"prompt": prompt, **kwargs})
        if self.complete_exc:
            raise self.complete_exc
        return self.complete_result or ""

    def generate_interpretation(self, **kwargs: Any) -> str:
        self.interp_calls.append(kwargs)
        section = kwargs["section_type"]
        if section in self.interp_fail:
            raise RuntimeError(f"{section} failed")
        return self.interp_results[section]


_FACTS = {
    "research_type": "cohort",
    "recommended_models": ["coxph", "rsf", "deepsurv"],
    "recommended_journals": ["JAMA", "BMJ"],
    "confidence": 0.92,
    "reasoning": "检测到随访时间列和0/1事件列",
    "n_rows": 120,
    "n_columns": 8,
    "columns": ["age", "os_months", "death"],
}


class TestSwitchMapping:
    def test_off_returns_none(self) -> None:
        assert switch_to_choice("off") is None

    def test_switch_to_model_choice(self) -> None:
        assert switch_to_choice("local") == "local"
        assert switch_to_choice("local_first") == "auto"
        assert switch_to_choice("cloud") == "cloud"


class TestResearchQuestions:
    def test_off_skips_llm(self) -> None:
        service = _StubService()
        assert generate_research_questions(service, _FACTS, "off") is None
        assert service.complete_calls == []

    def test_happy_path_parses_and_filters(self) -> None:
        raw = json.dumps(
            [
                {
                    "question": "年龄是否与 120 例患者的死亡风险相关？",
                    "design": "单因素 Cox 回归",
                    "models": ["coxph", "not_a_model"],
                    "charts": ["KM 生存曲线", "不存在的图"],
                },
                {
                    "question": "biomarker 水平能否预测生存时间？",
                    "design": "多因素 Cox 回归",
                    "models": ["rsf"],
                    "charts": ["HR 森林图"],
                },
            ],
            ensure_ascii=False,
        )
        service = _StubService(complete_result=raw)
        questions = generate_research_questions(service, _FACTS, "local")
        assert questions is not None and len(questions) == 2
        assert questions[0]["models"] == ["coxph"]  # 白名单外模型被过滤
        assert questions[0]["charts"] == ["KM 生存曲线"]

    def test_invalid_json_returns_none(self) -> None:
        service = _StubService(complete_result="这不是 JSON")
        assert generate_research_questions(service, _FACTS, "local") is None

    def test_hallucinated_number_drops_question(self) -> None:
        raw = json.dumps(
            [
                {
                    "question": "基于 9999 例样本的分析是否可靠？",  # 9999 不在 facts
                    "design": "队列研究",
                    "models": ["coxph"],
                    "charts": ["KM 生存曲线"],
                },
                {
                    "question": "年龄是否与死亡风险相关？",
                    "design": "单因素 Cox 回归",
                    "models": ["coxph"],
                    "charts": ["KM 生存曲线"],
                },
            ],
            ensure_ascii=False,
        )
        service = _StubService(complete_result=raw)
        questions = generate_research_questions(service, _FACTS, "local")
        assert questions is not None and len(questions) == 1
        assert "9999" not in questions[0]["question"]

    def test_all_hallucinated_returns_none(self) -> None:
        raw = json.dumps(
            [{"question": "样本量 8888 是否足够？", "design": "队列", "models": [], "charts": []}],
            ensure_ascii=False,
        )
        service = _StubService(complete_result=raw)
        assert generate_research_questions(service, _FACTS, "cloud") is None

    def test_llm_failure_falls_back_to_none(self) -> None:
        service = _StubService(complete_exc=RuntimeError("ollama down"))
        assert generate_research_questions(service, _FACTS, "local_first") is None


class TestReportInterpretations:
    _RESULTS: ClassVar[dict[str, str]] = {
        "model_comparison": "段落A",
        "performance": "段落B",
        "clinical_interpretation": "段落C",
    }
    _FACTS_BY_SECTION: ClassVar[dict[str, dict[str, Any]]] = {
        "model_comparison": {"ranking": ["rf", "logreg"], "auc_best": 0.87},
        "performance": {"auc": 0.87, "note": "p=0.032 差异有统计学意义"},
        "clinical_interpretation": {"top_features": ["age"]},
    }

    def test_off_returns_empty(self) -> None:
        service = _StubService(interp_results=self._RESULTS)
        assert generate_report_interpretations(service, self._FACTS_BY_SECTION, "off") == {}
        assert service.interp_calls == []

    def test_per_section_failure_isolated(self) -> None:
        service = _StubService(interp_results=self._RESULTS, interp_fail={"performance"})
        out = generate_report_interpretations(service, self._FACTS_BY_SECTION, "local")
        assert out == {"model_comparison": "段落A", "clinical_interpretation": "段落C"}

    def test_citable_numbers_include_text_numbers(self) -> None:
        """结论字符串里的真实数字（p=0.032）必须进入合法数值域，防误杀。"""
        service = _StubService(interp_results=self._RESULTS)
        generate_report_interpretations(service, self._FACTS_BY_SECTION, "local")
        perf_call = next(c for c in service.interp_calls if c["section_type"] == "performance")
        citable = perf_call["facts"]["citable_numbers"]
        assert 0.87 in citable and 0.032 in citable

    def test_all_failed_returns_empty(self) -> None:
        service = _StubService(
            interp_results=self._RESULTS, interp_fail=set(self._FACTS_BY_SECTION)
        )
        assert generate_report_interpretations(service, self._FACTS_BY_SECTION, "cloud") == {}


class TestExplainValidationIssues:
    def _issues(self) -> list[dict[str, Any]]:
        return [
            {
                "rule_id": "RV201",
                "severity": "blocker",
                "column": "bmi",
                "message": "缺失率 55%",
                "suggestion": "中位数填补",
                "affected_rows": 66,
                "guidance": "列「bmi」缺失值过多（55.0%）",
            },
            {"rule_id": "RV501", "severity": "warning", "column": "age", "message": "异常值"},
        ]

    def test_off_no_mutation(self) -> None:
        service = _StubService(complete_result="这是一段通俗解释。")
        issues = self._issues()
        assert explain_validation_issues(service, issues, "off") == 0
        assert "llm_explanation" not in issues[0]

    def test_only_blockers_explained(self) -> None:
        text = "这一列有超过一半的记录是空的，建议用中间值补上后再继续分析，这样结果会更稳。"
        service = _StubService(complete_result=text)
        issues = self._issues()
        assert explain_validation_issues(service, issues, "local") == 1
        assert issues[0]["llm_explanation"] == text
        assert "llm_explanation" not in issues[1]  # warning 不处理
        assert len(service.complete_calls) == 1

    def test_bad_length_skipped(self) -> None:
        service = _StubService(complete_result="太短。")
        issues = self._issues()
        assert explain_validation_issues(service, issues, "local") == 0
        assert "llm_explanation" not in issues[0]

    def test_hallucinated_number_skipped(self) -> None:
        service = _StubService(
            complete_result="这一列有 12345 条记录存在问题，建议删除后重新上传数据再试一次看看。"
        )
        issues = self._issues()
        assert explain_validation_issues(service, issues, "local") == 0

    def test_real_numbers_accepted(self) -> None:
        service = _StubService(
            complete_result="这一列有 66 行是空的，缺失比例 55%，建议用中间值补齐后重新分析。"
        )
        issues = self._issues()
        assert explain_validation_issues(service, issues, "local") == 1

    def test_llm_failure_skips_issue(self) -> None:
        service = _StubService(complete_exc=RuntimeError("down"))
        issues = self._issues()
        assert explain_validation_issues(service, issues, "cloud") == 0


@pytest.fixture()
def sync_db(monkeypatch: pytest.MonkeyPatch):
    """worker 同步会话指向测试库（与 test_analysis_orchestration.worker_sync_db 同款）。

    sync 写入不受 async 测试会话回滚约束，teardown 显式清理 admin_settings，
    避免运行层配置泄漏到其他测试。
    """
    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(worker_db, "_factory", factory)
    with factory() as db:
        yield db
    with factory() as db:
        for row in db.execute(select(AdminSetting)).scalars():
            db.delete(row)
        db.commit()


def _enable_switch(sync_db: Any, name: str, value: str) -> None:
    row = sync_db.get(AdminSetting, "llm.feature_switches")
    if row is None:
        sync_db.add(
            AdminSetting(
                key="llm.feature_switches", value=json.dumps({name: value}), is_secret=False
            )
        )
    else:
        row.value = json.dumps({name: value})
    sync_db.commit()


def _payload() -> dict[str, Any]:
    return {
        "run": {"task_type": "classification"},
        "table": [
            {
                "model_key": "rf",
                "status": "SUCCESS",
                "metrics": {"auc": {"mean": 0.87, "std": 0.01}},
                "p_value_text": "参考",
            }
        ],
        "comparison": {
            "ranking": ["rf"],
            "recommendation": {
                "top": [{"model_key": "rf", "rank": 1, "reason": "主指标最高"}],
                "not_recommended": [],
                "primary_metric": "auc",
            },
            "charts": [],
        },
    }


class TestReportWiring:
    def test_off_by_default_returns_none(self, sync_db: Any) -> None:
        assert report_tasks._llm_interpretations(sync_db, _payload()) is None

    def test_enabled_calls_llm_tasks(self, sync_db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_switch(sync_db, "report_interpretation", "local")
        monkeypatch.setattr(report_tasks, "init_llm_service_from_runtime", lambda cfg: object())
        captured: dict[str, Any] = {}

        def fake(service: Any, facts: Any, switch: Any, temperature: Any) -> dict[str, str]:
            captured.update({"facts": facts, "switch": switch, "temperature": temperature})
            return {"model_comparison": "段落"}

        monkeypatch.setattr(llm_tasks, "generate_report_interpretations", fake)
        out = report_tasks._llm_interpretations(sync_db, _payload())
        assert out == {"model_comparison": "段落"}
        assert captured["switch"] == "local"
        assert (
            captured["facts"]["model_comparison"]["performance"][0]["metrics"]["auc"]["mean"]
            == 0.87
        )

    def test_llm_failure_returns_none(self, sync_db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_switch(sync_db, "report_interpretation", "local")
        monkeypatch.setattr(report_tasks, "init_llm_service_from_runtime", lambda cfg: object())
        monkeypatch.setattr(
            llm_tasks,
            "generate_report_interpretations",
            lambda *a: {},  # 全失败
        )
        assert report_tasks._llm_interpretations(sync_db, _payload()) is None

    def test_facts_trim_diagnostics(self) -> None:
        payload = _payload()
        payload["diagnostics"] = {
            "model_key": "rf",
            "shapiro": {"statistic": 0.98, "p_value": 0.4, "conclusion": "残差近似正态"},
            "coefficients": [{"term": f"x{i}", "coef": 0.1} for i in range(20)],
            "vif": {"conclusion": "无共线性", "vif_values": {f"x{i}": 1.1 for i in range(20)}},
        }
        facts = report_tasks._interpretation_facts(payload)
        diag = facts["performance"]["diagnostics"]
        assert len(diag["coefficients_top"]) == 5  # 截断到 5
        assert len(diag["vif"]["vif_values"]) == 10
        assert "coefficients" not in diag


class TestDatasetWiring:
    def _issues(self) -> list[dict[str, Any]]:
        return [{"rule_id": "RV201", "severity": "blocker", "column": "bmi", "message": "缺失"}]

    def test_off_by_default_no_explanation(self, sync_db: Any) -> None:
        issues = self._issues()
        dataset_tasks._explain_blockers(sync_db, issues)
        assert "llm_explanation" not in issues[0]

    def test_enabled_writes_explanation(
        self, sync_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_switch(sync_db, "validation_explain", "local")
        monkeypatch.setattr(dataset_tasks, "init_llm_service_from_runtime", lambda cfg: object())

        def fake(service: Any, issues: Any, switch: Any, temperature: Any) -> int:
            issues[0]["llm_explanation"] = "通俗解释"
            return 1

        monkeypatch.setattr(llm_tasks, "explain_validation_issues", fake)
        issues = self._issues()
        dataset_tasks._explain_blockers(sync_db, issues)
        assert issues[0]["llm_explanation"] == "通俗解释"
