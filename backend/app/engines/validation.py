"""校验规则引擎（docs/05 §3 共 17 条规则）+ 质量报告（docs/14 QualityReport 契约）。

流水线位置：解析（engines/parser）→ 列类型/语义（engines/columns）→ 本模块规则
执行 → 列质量画像 → QualityReport 落库（workers/dataset_tasks）。
阈值集中于 ValidationConfig（docs/05 §6，项目级可覆盖）。

分层纪律：engines 只依赖数据处理库，禁止 import fastapi/celery/sqlalchemy。
"""

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.engines.columns import infer_dtype, recognize_semantic
from app.engines.validation_messages import get_optimized_suggestion

# ---------- 配置（05 §6：所有阈值集中，项目级可覆盖） ----------


@dataclass(frozen=True)
class ValidationConfig:
    missing_warn: float = 0.2  # RV201 警告阈值
    missing_block: float = 0.5  # RV201 阻塞阈值
    high_cardinality: int = 50  # RV601
    imbalance_ratio: float = 0.05  # RV701
    iqr_k: float = 1.5  # RV501 IQR 系数
    extreme_abs: float = 1e6  # RV804 极端值阈值（绝对值）
    susceptibility_min_rows: int = 5  # RV802 药敏判定最少行数
    prepared_output: bool = False  # 数据准备产物模式（docs/05 §8.5）：RV201 阻塞降级为警告


# ---------- 输出结构（14 章 QualityReport 契约） ----------


@dataclass
class Issue:
    rule_id: str
    severity: str  # blocker / critical / warning / info（updateplan §15 四级；critical=须人工复核但暂不阻断）
    message: str
    column: str | None = None
    suggestion: str = ""
    detail: str = ""
    affected_rows: int | None = None
    # T6.1:受影响行号(0 基,升序,采样式上限 _ROW_INDEX_CAP);非行级规则为 None
    row_indices: list[int] | None = None
    # T6.1:富文案修复指引(原因+多种修法+一键操作;validation_messages)
    guidance: str = ""
    # P2-3:结构化修复指引(问题→影响→修法列表,修法含一键动作契约;fix_guidance)
    fix_guidance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "column": self.column,
            "message": self.message,
            "detail": self.detail,
            "suggestion": self.suggestion,
            "affected_rows": self.affected_rows,
            "row_indices": self.row_indices,
            "guidance": self.guidance,
            "fix_guidance": self.fix_guidance,
        }


@dataclass
class ValidationReport:
    status: str  # PASSED / PASSED_WITH_WARNINGS / FAILED（14 章枚举）
    blockers: int
    warnings: int
    criticals: int = 0  # updateplan §15 CRITICAL 档计数
    issues: list[Issue] = field(default_factory=list)
    column_profiles: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "criticals": self.criticals,
            "issues": [i.to_dict() for i in self.issues],
            "column_profiles": self.column_profiles,
            "summary": self.summary,
        }


def parse_error_issue(encoding_hint: str | None = None) -> Issue:
    """RV001：文件无法解析（由解析失败的调用方生成）。"""
    hint = (encoding_hint or "GBK").upper()
    suggestion = get_optimized_suggestion("RV001", {"encoding_hint": hint})
    return Issue(
        "RV001",
        "blocker",
        "文件无法解析（编码/格式错误）",
        suggestion=suggestion,
        guidance=suggestion,
    )


# ---------- 内置临床合理范围词典（RV502；docs/05 §3） ----------

_CLINICAL_RANGES: list[tuple[tuple[str, ...], float, float, str]] = [
    (("血钾", "potassium"), 2.5, 6.5, "mmol/L"),
    (("血钠", "sodium"), 125.0, 155.0, "mmol/L"),
    (("白细胞", "wbc"), 0.5, 100.0, "10^9/L"),
    (("血小板", "plt", "platelet"), 10.0, 1500.0, "10^9/L"),
    (("血红蛋白", "hgb", "hemoglobin"), 30.0, 220.0, "g/L"),
    (("肌酐", "creatinine"), 10.0, 2000.0, "µmol/L"),
    (("血糖", "glucose"), 1.0, 40.0, "mmol/L"),
    (("收缩压", "sbp"), 50.0, 300.0, "mmHg"),
    (("舒张压", "dbp"), 20.0, 200.0, "mmHg"),
    (("心率", "heartrate"), 20.0, 250.0, "次/分"),
    (("体温", "temperature"), 30.0, 44.0, "℃"),
    (("血氧", "spo2"), 50.0, 100.0, "%"),
]
_AGE_RANGE = (0.0, 120.0)

_ID_NAME_RE = re.compile(
    r"(^|[^a-z0-9一-鿿])(id|no|num)([^a-z0-9一-鿿]|$)|编号|住院号|病历号", re.I
)

# ---------- RV8xx 临床数据模式（docs/05 §3，2026-08-03 新增） ----------
# 仅当对应列名模式存在时触发；宽表上传不受影响。

_ITEM_COLS = {"检验名称", "检验项目", "项目名称", "检查项目", "项目", "test_name", "item_name"}
_VALUE_COLS = {"结果", "检验结果", "测定值", "result", "value"}
_UNIT_COLS = {"化验单位", "检验单位", "单位", "unit"}
_SUS_COLS = {"异常", "药敏", "结果判定", "判定", "susceptibility"}
_SUS_VALUE_RE = re.compile(r"敏感|耐药|中介")


def _find_col(df: pd.DataFrame, candidates: set[str]) -> int | None:
    """按列名（去空格，英文小写）找第一个匹配列的位置索引；无则 None。"""
    for i, c in enumerate(df.columns):
        name = str(c).strip()
        if name in candidates or name.lower() in candidates:
            return i
    return None


def _tokens(name: str) -> set[str]:
    token, tokens = [], []
    for ch in str(name).lower():
        if ch.isalnum():
            token.append(ch)
        elif token:
            tokens.append("".join(token))
            token = []
    if token:
        tokens.append("".join(token))
    return set(tokens)


def _is_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _match_clinical_range(name: str) -> tuple[float, float, str] | None:
    tokens = _tokens(name)
    for aliases, low, high, unit in _CLINICAL_RANGES:
        for alias in aliases:
            if _is_cjk(alias):
                if alias in str(name):
                    return low, high, unit
            elif alias in tokens:
                return low, high, unit
    return None


# ---------- P1-01 变量字典字段（updateplan §11） ----------
# 参考范围只允许确定性来源：domain_knowledge（内置词典）/ dataset_inferred
# （观测范围，非医学参考）/ user_defined（用户定义）；禁止 LLM 凭空生成。

_CLINICAL_ROLE_BY_SEMANTIC = {
    "Event": "outcome",
    "Label": "outcome",
    "FollowUp": "time",
    "Age": "baseline",
    "Gender": "baseline",
    "Diagnosis": "baseline",
}


def _clinical_role(semantic: str | None, dtype: str) -> str:
    """语义/类型 → 临床角色（identifier/outcome/time/baseline/covariate）。"""
    if dtype == "id":
        return "identifier"
    return _CLINICAL_ROLE_BY_SEMANTIC.get(semantic or "", "covariate")


def _timepoint(semantic: str | None) -> str:
    """语义 → 采集时点启发式：结局=T1，随访=T1+，其余=T0（基线）。"""
    if semantic in ("Event", "Label"):
        return "T1"
    if semantic == "FollowUp":
        return "T1+"
    return "T0"


def _reference_range(
    name: str, semantic: str | None, dtype: str, s_num: pd.Series
) -> dict[str, Any] | None:
    """连续列参考范围：内置临床词典/年龄 → domain_knowledge；否则观测范围 → dataset_inferred。"""
    if dtype != "continuous":
        return None
    rng = _match_clinical_range(name)
    if rng is None and semantic == "Age":
        rng = (*_AGE_RANGE, "岁")
    if rng is not None:
        low, high, unit = rng
        return {"low": low, "high": high, "unit": unit, "source": "domain_knowledge"}
    non_null = s_num.dropna()
    if not len(non_null):
        return None
    return {
        "low": _native(non_null.min()),
        "high": _native(non_null.max()),
        "unit": None,
        "source": "dataset_inferred",
    }


def _native(v: Any) -> Any:
    return v.item() if hasattr(v, "item") else v


def _iqr_outliers(s_num: pd.Series, k: float) -> pd.Series:
    """返回布尔 mask（True=异常）。IQR=0 时不判异常。"""
    clean = s_num.dropna()
    if len(clean) < 4:
        return pd.Series(False, index=s_num.index)
    q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return pd.Series(False, index=s_num.index)
    return (s_num < q1 - k * iqr) | (s_num > q3 + k * iqr)


# ---------- T6.1 富文案 + 行号后处理（validation_messages 接线） ----------

_ROW_INDEX_CAP = 20  # row_indices 采样上限（前端展示 Excel 行号 = 索引 + 2）

# RV102 推荐字段清单（创建与富文案重建共用单一来源）
_RECOMMENDED_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("Age", "年龄", "可支持按年龄段分层分析（如不同年龄组的风险差异）"),
    ("Gender", "性别", "可支持按性别分层分析"),
)


def _col_by_name(df: pd.DataFrame, name: str) -> pd.Series | None:
    """按列名安全取列；重名列（RV003 场景）返回 None 避免歧义。"""
    if list(df.columns).count(name) != 1:
        return None
    return df[name]


def _row_indices_for(issue: Issue, df: pd.DataFrame, cfg: ValidationConfig) -> list[int] | None:
    """行级规则反推受影响行号（0 基，升序，≤_ROW_INDEX_CAP）；非行级规则返回 None。"""
    mask: pd.Series | None = None
    if issue.rule_id == "RV401" and issue.column is None:
        mask = df.duplicated(keep="first")
    elif issue.column is not None:
        s = _col_by_name(df, issue.column)
        if s is None:
            return None
        s_num = pd.to_numeric(s, errors="coerce")
        if issue.rule_id == "RV201":
            mask = s.isna()
        elif issue.rule_id == "RV301":
            mask = s_num.isna() & s.notna()
        elif issue.rule_id == "RV401":
            mask = s.notna() & s.duplicated(keep="first")
        elif issue.rule_id == "RV501":
            mask = _iqr_outliers(s_num, cfg.iqr_k)
        elif issue.rule_id == "RV502":
            rng = _match_clinical_range(issue.column)
            if rng is None and recognize_semantic(issue.column, s).semantic == "Age":
                rng = (*_AGE_RANGE, "岁")
            if rng is not None:
                low, high, _ = rng
                mask = (s_num < low) | (s_num > high)
        elif issue.rule_id == "RV804":
            mask = s_num.abs() > cfg.extreme_abs
        elif issue.rule_id == "RV802":
            mask = s.astype(str).str.contains(_SUS_VALUE_RE) & s.notna()
    if mask is None:
        return None
    idx = [int(i) for i in df.index[mask.fillna(False)]]
    return sorted(idx)[:_ROW_INDEX_CAP] or None


def _guidance_for(
    issue: Issue,
    df: pd.DataFrame,
    n_rows: int,
    extra: dict[str, Any],
) -> str:
    """按 rule_id 生成富文案；validation.py 规则号 → validation_messages 生成器映射。"""
    rid = issue.rule_id
    col = issue.column or ""
    ctx: dict[str, Any]
    if rid == "RV101":
        return get_optimized_suggestion("RV701")  # 缺目标变量
    if rid == "RV102":
        field_name = issue.message.rsplit("：", 1)[-1]
        for name, zh, advice in _RECOMMENDED_FIELDS:
            if name == field_name:
                return get_optimized_suggestion(
                    "RV702", {"field_name": name, "field_zh": zh, "advice": advice}
                )
        return get_optimized_suggestion("RV702", {"field_name": field_name})
    if rid == "RV302":
        return get_optimized_suggestion("RV401", {"column": col})  # 日期格式
    if rid == "RV401":
        if issue.column is None:
            return get_optimized_suggestion("RV704", {"duplicate_count": issue.affected_rows or 0})
        return get_optimized_suggestion(
            "RV705", {"suspect_count": issue.affected_rows or 0, "id_column": col}
        )
    if rid == "RV701":
        ratio = (issue.affected_rows or 0) / n_rows if n_rows else 0.0
        return get_optimized_suggestion("RV703", {"minority_ratio": ratio})
    if rid == "RV003":
        return get_optimized_suggestion("RV003", {"duplicates": extra.get("dup_names", [])})
    if rid == "RV201":
        ctx = {
            "column": col,
            "missing_rate": (issue.affected_rows or 0) / n_rows if n_rows else 0.0,
            "severity": issue.severity,
        }
    elif rid == "RV301":
        ctx = {"column": col, "invalid_count": issue.affected_rows or 0}
    elif rid == "RV501":
        ctx = {"column": col, "outlier_count": issue.affected_rows or 0}
    elif rid == "RV502":
        rng = _match_clinical_range(col)
        s = _col_by_name(df, col)
        if rng is None and s is not None and recognize_semantic(col, s).semantic == "Age":
            rng = (*_AGE_RANGE, "岁")
        ctx = {
            "column": col,
            "unreasonable_count": issue.affected_rows or 0,
            "expected_range": f"{rng[0]}–{rng[1]} {rng[2]}" if rng else "",
        }
        if s is not None:
            s_num = pd.to_numeric(s, errors="coerce").dropna()
            if len(s_num):
                ctx["min_val"], ctx["max_val"] = _native(s_num.min()), _native(s_num.max())
    elif rid == "RV601":
        s = _col_by_name(df, col)
        ctx = {"column": col, "unique_count": int(s.nunique()) if s is not None else 0}
    elif rid == "RV801":
        ctx = {
            "item_column": extra.get("item_col", "检验项目"),
            "value_column": extra.get("value_col", "结果"),
        }
    elif rid == "RV802":
        ctx = {"sus_column": extra.get("sus_col", col), "sus_count": issue.affected_rows or 0}
    elif rid == "RV803":
        ctx = {"examples": extra.get("unit_examples", [])}
    elif rid == "RV804":
        s = _col_by_name(df, col)
        extreme = 0.0
        if s is not None:
            s_num = pd.to_numeric(s, errors="coerce").dropna()
            if len(s_num):
                extreme = float(max(abs(s_num.min()), abs(s_num.max())))
        ctx = {"column": col, "extreme": extreme}
    else:
        ctx = {}
    return get_optimized_suggestion(rid, ctx)


def _enrich_issues(
    issues: list[Issue], df: pd.DataFrame, cfg: ValidationConfig, extra: dict[str, Any]
) -> None:
    """原地为每条 Issue 补 guidance（富文案）、fix_guidance（结构化）与 row_indices。"""
    from app.engines.fix_guidance import fix_guidance_for

    n_rows = len(df)
    for issue in issues:
        if not issue.guidance:
            issue.guidance = _guidance_for(issue, df, n_rows, extra)
        if issue.fix_guidance is None:
            issue.fix_guidance = fix_guidance_for(issue)
        if issue.row_indices is None:
            issue.row_indices = _row_indices_for(issue, df, cfg)


# ---------- 主入口 ----------


def validate(
    df: pd.DataFrame,
    *,
    config: ValidationConfig | None = None,
    raw_columns: list[str] | None = None,
) -> ValidationReport:
    """对解析后的 DataFrame 执行 13 条规则并生成质量报告。

    raw_columns：解析前的原始表头（pandas 会把重复列名改写为 a/a.1，
    RV003 需基于原始表头判定）；缺省用 df.columns。
    """
    cfg = config or ValidationConfig()
    issues: list[Issue] = []
    n_rows, n_cols = df.shape

    # RV002 空表
    if n_rows == 0:
        issues.append(
            Issue(
                "RV002", "blocker", "文件不含数据行", suggestion=get_optimized_suggestion("RV002")
            )
        )

    # RV003 重复列名（基于原始表头）
    cols = [str(c) for c in (raw_columns if raw_columns is not None else df.columns)]
    dup_names = sorted(
        {c for c, dup in zip(cols, pd.Series(cols).duplicated(), strict=True) if dup}
    )
    if dup_names:
        issues.append(
            Issue(
                "RV003",
                "blocker",
                f"列 {', '.join(dup_names)} 重复出现，请重命名",
                suggestion=get_optimized_suggestion("RV003", {"duplicates": dup_names}),
            )
        )

    # ---- 列分析（位置索引遍历，规避重复列名下 df[col] 返回 DataFrame） ----
    profiles: list[dict[str, Any]] = []
    semantics: dict[str, str | None] = {}
    dtypes: dict[str, str] = {}
    for i in range(n_cols):
        name = str(df.columns[i])
        s = df.iloc[:, i]
        dtype = infer_dtype(s)
        sem = recognize_semantic(name, s)
        missing = int(s.isna().sum())
        s_num = pd.to_numeric(s, errors="coerce")
        outlier_count = int(_iqr_outliers(s_num, cfg.iqr_k).sum()) if dtype == "continuous" else 0
        profile: dict[str, Any] = {
            "name": name,
            "inferred_type": dtype,
            "semantic": sem.semantic,
            "semantic_confidence": sem.confidence,
            "missing_rate": round(missing / n_rows, 4) if n_rows else 0.0,
            "unique": int(s.nunique()),
            "outliers": outlier_count,
            # P1-01 变量字典（updateplan §11）
            "clinical_role": _clinical_role(sem.semantic, dtype),
            "timepoint": _timepoint(sem.semantic),
            "reference_range": _reference_range(name, sem.semantic, dtype, s_num),
            "warnings": [],  # 规则执行完毕后回填（见函数末尾）
        }
        # 单位仅来自确定性来源（内置临床词典）；无命中留空待用户定义（§11 禁 LLM 生成）
        rr = profile["reference_range"]
        profile["unit"] = rr["unit"] if rr and rr["source"] == "domain_knowledge" else None
        if dtype == "continuous":
            non_null = s_num.dropna()
            if len(non_null):
                profile["min"] = _native(non_null.min())
                profile["max"] = _native(non_null.max())
        profiles.append(profile)
        semantics[name] = sem.semantic
        dtypes[name] = dtype

    found = {v for v in semantics.values() if v}

    # ---- RV8xx 临床数据模式（先于人话版 RV101，解释「为什么这张表没法直接分析」） ----
    item_idx = _find_col(df, _ITEM_COLS)
    value_idx = _find_col(df, _VALUE_COLS)
    unit_idx = _find_col(df, _UNIT_COLS)
    sus_idx = _find_col(df, _SUS_COLS)

    # RV801 长表结构（检验名称 + 结果 列组合）
    if n_rows > 0 and item_idx is not None and value_idx is not None:
        issues.append(
            Issue(
                "RV801",
                "warning",
                "检测到「一行一条记录」的长表结构",
                detail=f"列 {df.columns[item_idx]} + {df.columns[value_idx]} "
                "表明每行是一条检验/检查记录，而非一行一个患者",
                suggestion=get_optimized_suggestion(
                    "RV801",
                    {"item_column": df.columns[item_idx], "value_column": df.columns[value_idx]},
                ),
            )
        )

    # RV802 疑似药敏试验记录（判定列含 敏感/耐药/中介）
    if n_rows > 0 and sus_idx is not None:
        sus_vals = df.iloc[:, sus_idx].dropna().astype(str)
        n_sus = int(sus_vals.str.contains(_SUS_VALUE_RE).sum())
        if n_sus >= cfg.susceptibility_min_rows:
            issues.append(
                Issue(
                    "RV802",
                    "warning",
                    "检测到疑似药敏试验记录",
                    column=str(df.columns[sus_idx]),
                    detail=f"列 {df.columns[sus_idx]} 含 敏感/耐药/中介 判定值 {n_sus} 行",
                    affected_rows=n_sus,
                    suggestion=get_optimized_suggestion(
                        "RV802", {"sus_column": df.columns[sus_idx], "sus_count": n_sus}
                    ),
                )
            )

    # RV803 同一检验项目多种单位
    unit_examples: list[str] = []
    if n_rows > 0 and item_idx is not None and unit_idx is not None:
        tmp = df.iloc[:, [item_idx, unit_idx]].dropna()
        tmp.columns = pd.Index(["item", "unit"])
        unit_counts = tmp.groupby("item")["unit"].nunique().sort_values(ascending=False)
        multi = unit_counts[unit_counts > 1]
        if len(multi):
            top = "、".join(f"{k}（{v} 种）" for k, v in multi.head(3).items())
            unit_examples = [str(k) for k in multi.head(3).index]
            issues.append(
                Issue(
                    "RV803",
                    "warning",
                    "同一检验项目存在多种单位",
                    detail=f"如：{top}",
                    suggestion=get_optimized_suggestion(
                        "RV803", {"examples": list(multi.head(3).index)}
                    ),
                )
            )

    # RV804 数值列极端值（复用列画像 min/max，零额外开销）
    for p in profiles:
        if p.get("inferred_type") == "continuous" and p.get("min") is not None:
            extreme = max(abs(p["min"]), abs(p["max"]))
            if extreme > cfg.extreme_abs:
                issues.append(
                    Issue(
                        "RV804",
                        "warning",
                        f"列 {p['name']} 存在极端值（绝对值达 {extreme:g}），疑似单位或录入错误",
                        column=p["name"],
                        suggestion=get_optimized_suggestion(
                            "RV804", {"column": p["name"], "extreme": extreme}
                        ),
                    )
                )

    # RV101 任务必需字段缺失（降级为 warning，不再阻塞）
    # 用户可以在分析向导中手动选择目标列，或进入探索性分析模式
    if n_rows > 0 and not ({"Event", "Label", "FollowUp"} & found):
        issues.append(
            Issue(
                "RV101",
                "warning",  # 从 blocker 降级为 warning
                "未自动识别到预测目标列",
                detail=f"已扫描 {n_cols} 列，未识别到结局/事件/随访时间列。"
                "您可以在下一步手动选择目标列，或进行探索性分析（EDA）",
                suggestion=get_optimized_suggestion("RV701"),
            )
        )

    # RV102 推荐字段缺失
    for field_name, zh, advice in _RECOMMENDED_FIELDS:
        if field_name not in found:
            issues.append(
                Issue(
                    "RV102",
                    "warning",
                    f"推荐字段缺失：{field_name}",
                    suggestion=get_optimized_suggestion(
                        "RV702", {"field_name": field_name, "field_zh": zh, "advice": advice}
                    ),
                )
            )

    for i in range(n_cols):
        name = str(df.columns[i])
        s = df.iloc[:, i]
        dtype = dtypes[name]
        missing = int(s.isna().sum())
        s_num = pd.to_numeric(s, errors="coerce")

        # RV201 缺失率
        if n_rows and missing:
            rate = missing / n_rows
            if rate > cfg.missing_block and not cfg.prepared_output:
                issues.append(
                    Issue(
                        "RV201",
                        "blocker",
                        f"列 {name} 缺失 {rate:.1%}，建议删除或插补",
                        column=name,
                        affected_rows=missing,
                        suggestion=get_optimized_suggestion(
                            "RV201", {"column": name, "missing_rate": rate, "severity": "blocker"}
                        ),
                    )
                )
            elif rate > cfg.missing_warn:
                issues.append(
                    Issue(
                        "RV201",
                        "warning",
                        f"列 {name} 缺失 {rate:.1%}",
                        column=name,
                        affected_rows=missing,
                        suggestion=get_optimized_suggestion(
                            "RV201", {"column": name, "missing_rate": rate, "severity": "warning"}
                        ),
                    )
                )

        # RV301 数值列混入非法值（≥90% 可转数值 → 数值意图）
        if s.dtype == object and n_rows:
            numeric_ratio = s_num.notna().mean()
            illegal = int(((s_num.isna()) & s.notna()).sum())
            if numeric_ratio >= 0.9 and illegal > 0:
                issues.append(
                    Issue(
                        "RV301",
                        "blocker",
                        f"列 {name} 发现 {illegal} 个非数值，可在线替换为缺失",
                        column=name,
                        affected_rows=illegal,
                        suggestion=get_optimized_suggestion(
                            "RV301", {"column": name, "invalid_count": illegal}
                        ),
                    )
                )

        # RV302 日期格式不一致
        if dtype == "datetime" and s.dtype == object:
            patterns = {re.sub(r"\d", "9", str(v)) for v in s.dropna()}
            if len(patterns) >= 2:
                issues.append(
                    Issue(
                        "RV302",
                        "warning",
                        f"列 {name} 检测到 {len(patterns)} 种日期格式",
                        column=name,
                        suggestion=get_optimized_suggestion("RV401", {"column": name}),
                    )
                )

        # RV502 临床不合理范围（先于 RV501，命中则 RV501 跳过该列避免重复报告）
        range_flagged = False
        if dtype == "continuous":
            rng = _match_clinical_range(name)
            if rng is None and semantics[name] == "Age":
                rng = (*_AGE_RANGE, "岁")
            if rng is not None:
                low, high, unit = rng
                out = s_num[(s_num < low) | (s_num > high)].dropna()
                if len(out):
                    range_flagged = True
                    issues.append(
                        Issue(
                            "RV502",
                            # updateplan §16（P0-04）：临床不合理范围（如 age=598）
                            # 不是普通统计异常值，须人工复核 → critical 档
                            "critical",
                            f"{name} 存在 {len(out)} 个值超出合理范围（{low}–{high} {unit}），"
                            f"最小值 {_native(out.min())}",
                            column=name,
                            affected_rows=len(out),
                            suggestion=get_optimized_suggestion(
                                "RV502",
                                {
                                    "column": name,
                                    "unreasonable_count": len(out),
                                    "min_val": _native(out.min()),
                                    "max_val": _native(out.max()),
                                    "expected_range": f"{low}–{high} {unit}",
                                },
                            ),
                        )
                    )

        # RV501 IQR 异常值
        if dtype == "continuous" and not range_flagged:
            n_out = int(_iqr_outliers(s_num, cfg.iqr_k).sum())
            if n_out:
                issues.append(
                    Issue(
                        "RV501",
                        "warning",
                        f"{name} 存在 {n_out} 个异常值（IQR×{cfg.iqr_k}）",
                        column=name,
                        affected_rows=n_out,
                        suggestion=get_optimized_suggestion(
                            "RV501", {"column": name, "outlier_count": n_out}
                        ),
                    )
                )

        # RV601 高基数分类
        if dtype in {"categorical", "text"} and s.nunique() > cfg.high_cardinality:
            issues.append(
                Issue(
                    "RV601",
                    "info",
                    f"列 {name} 唯一值 {s.nunique()} 个，建议合并或视为文本",
                    column=name,
                    suggestion=get_optimized_suggestion(
                        "RV601", {"column": name, "unique_count": s.nunique()}
                    ),
                )
            )

        # RV701 标签极端不平衡
        if semantics[name] in {"Event", "Label"} and dtype == "categorical":
            non_null = s.dropna()
            if len(non_null):
                min_rate = float(non_null.value_counts(normalize=True).min())
                if min_rate < cfg.imbalance_ratio:
                    issues.append(
                        Issue(
                            "RV701",
                            "warning",
                            f"{name} 阳性率 {min_rate:.1%}，建议使用 class_weight 与 PR-AUC",
                            column=name,
                            suggestion=get_optimized_suggestion(
                                "RV703", {"minority_ratio": min_rate}
                            ),
                        )
                    )

    # RV401 完全重复行 / ID 列重复
    full_dup = int(df.duplicated().sum())
    if full_dup:
        issues.append(
            Issue(
                "RV401",
                "warning",
                f"发现 {full_dup} 行完全重复，可在线去重",
                affected_rows=full_dup,
                suggestion=get_optimized_suggestion("RV704", {"duplicate_count": full_dup}),
            )
        )
    for i in range(n_cols):
        name = str(df.columns[i])
        if _ID_NAME_RE.search(name):
            n_dup = int(df.iloc[:, i].dropna().duplicated().sum())
            if n_dup:
                issues.append(
                    Issue(
                        "RV401",
                        "warning",
                        f"ID 列 {name} 有 {n_dup} 个重复值，疑似同一患者重复",
                        column=name,
                        affected_rows=n_dup,
                        suggestion=get_optimized_suggestion(
                            "RV705", {"suspect_count": n_dup, "id_column": name}
                        ),
                    )
                )

    blockers = sum(1 for i in issues if i.severity == "blocker")
    criticals = sum(1 for i in issues if i.severity == "critical")
    warnings = sum(1 for i in issues if i.severity == "warning")
    # critical 不阻断（阻断仍属 blocker），但计入警示状态（updateplan §15-16）
    status = "FAILED" if blockers else ("PASSED_WITH_WARNINGS" if (warnings or criticals) else "PASSED")
    # T6.1:统一补富文案指引与受影响行号(docs/05 §3,tasks/phase6 T6.1)
    _enrich_issues(
        issues,
        df,
        cfg,
        {
            "dup_names": dup_names,
            "item_col": str(df.columns[item_idx]) if item_idx is not None else "",
            "value_col": str(df.columns[value_idx]) if value_idx is not None else "",
            "sus_col": str(df.columns[sus_idx]) if sus_idx is not None else "",
            "unit_examples": unit_examples,
        },
    )
    # P1-01（§11）：规则执行完毕后回填每列 warnings（命中的 rule_id 列表）
    for p in profiles:
        p["warnings"] = [i.rule_id for i in issues if i.column == p["name"]]
    return ValidationReport(
        status=status,
        blockers=blockers,
        warnings=warnings,
        criticals=criticals,
        issues=issues,
        column_profiles=profiles,
        summary={
            "rows": n_rows,
            "columns": n_cols,
            "blockers": blockers,
            "warnings": warnings,
            "criticals": criticals,
        },
    )
