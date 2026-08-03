"""数据准备引擎（docs/05 §8）：长表（化验）+ 诊断表 → 宽表（一行一患者）。

设计原则：
- 机器做苦力（剔药敏/截断/防泄漏取值/透视合并），医生只做选择题（PrepDecisions）。
- 防泄漏为硬规则：仅保留 化验日期 ≤ 索引诊断日期 的记录（不可关闭）。
- 每阶段行数变化写入 summary，可审计（结果真实红线）。

分层纪律：engines 只依赖数据处理库，禁止 import fastapi/celery/sqlalchemy。
"""

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# ---------- 列名候选（与 validation RV8xx 同源语义，引擎自持有以解耦） ----------

_ID_COLS = {"患者id", "patient_id", "患者编号", "病案号", "住院号"}
_ITEM_COLS = {"检验名称", "检验项目", "项目名称", "检查项目", "项目", "test_name", "item_name"}
_LAB_DATE_COLS = {"化验日期", "检验日期", "检查日期", "采样日期", "test_date"}
_SPECIMEN_COLS = {"检验标本", "标本", "sample_type", "specimen"}
_SUS_COLS = {"异常", "药敏", "结果判定", "判定", "susceptibility"}
_UNIT_COLS = {"化验单位", "检验单位", "单位", "unit"}
_DIAG_DATE_COLS = {"诊断日期", "诊断时间", "diagnosis_date"}
_DIAG_TEXT_COLS = {"诊断", "疾病诊断", "diagnosis", "dx"}
_AGE_COLS = {"年龄", "age"}
_SEX_COLS = {"性别", "gender", "sex"}
_NORM_VALUE_COLS = ("归一化值", "结果值", "结果", "result", "value")

_SUS_VALUE_RE = re.compile(r"敏感|耐药|中介")


def _find_col(df: pd.DataFrame, candidates: set[str]) -> str | None:
    for c in df.columns:
        name = str(c).strip()
        if name in candidates or name.lower() in candidates:
            return str(c)
    return None


def _norm_term(t: str) -> str:
    return str(t).strip().lstrip("~").strip()


def _norm_text(t: Any) -> str:
    return str(t).replace("~", "") if pd.notna(t) else ""


# ---------- 决策与产物 ----------


@dataclass(frozen=True)
class PrepDecisions:
    """docs/05 §8.2 五个决策点（+引擎参数）。"""

    outcome_terms: tuple[str, ...]  # D1 结局阳性词条（任一命中=1，子串匹配）
    outcome_scope: str = "any"  # D2 any=任一诊断记录 | index=仅索引诊断
    index_diagnosis: str = "first"  # D3 first=首次 | last=末次
    window_days: int = 30  # D4 诊断前 N 天；0=不限
    value_strategy: str = "latest"  # D5 latest=最近一次 | mean=均值
    value_column: str = "归一化值"
    exclude_susceptibility: bool = True
    clip_quantile: float = 0.99  # 按项目 winsorize；0=不截断
    top_n_items: int = 200


@dataclass
class PrepPreview:
    lab_columns: dict[str, str | None]
    diag_columns: dict[str, str | None]
    lab_rows: int
    diag_rows: int
    patients_intersection: int
    diagnosis_terms: list[dict[str, Any]]
    susceptibility_rows: int
    suggested: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lab_columns": self.lab_columns,
            "diag_columns": self.diag_columns,
            "lab_rows": self.lab_rows,
            "diag_rows": self.diag_rows,
            "patients_intersection": self.patients_intersection,
            "diagnosis_terms": self.diagnosis_terms,
            "susceptibility_rows": self.susceptibility_rows,
            "suggested": self.suggested,
        }


@dataclass
class PrepResult:
    wide: pd.DataFrame
    summary: dict[str, Any]


# ---------- 扫描（preview） ----------


def scan(lab_df: pd.DataFrame, diag_df: pd.DataFrame, term_limit: int = 100) -> PrepPreview:
    lab_cols = {
        "id": _find_col(lab_df, _ID_COLS),
        "item": _find_col(lab_df, _ITEM_COLS),
        "date": _find_col(lab_df, _LAB_DATE_COLS),
        "unit": _find_col(lab_df, _UNIT_COLS),
        "specimen": _find_col(lab_df, _SPECIMEN_COLS),
        "susceptibility": _find_col(lab_df, _SUS_COLS),
    }
    value_col = next((c for c in _NORM_VALUE_COLS if c in lab_df.columns), None)
    lab_cols["value"] = value_col

    diag_cols = {
        "id": _find_col(diag_df, _ID_COLS),
        "date": _find_col(diag_df, _DIAG_DATE_COLS),
        "text": _find_col(diag_df, _DIAG_TEXT_COLS),
        "age": _find_col(diag_df, _AGE_COLS),
        "sex": _find_col(diag_df, _SEX_COLS),
    }

    terms: dict[str, int] = {}
    if diag_cols["text"]:
        for cell in diag_df[diag_cols["text"]].dropna():
            for t in str(cell).split(";"):
                t = _norm_term(t)
                if t:
                    terms[t] = terms.get(t, 0) + 1
    top_terms = [
        {"term": k, "count": v}
        for k, v in sorted(terms.items(), key=lambda kv: -kv[1])[:term_limit]
    ]

    sus_rows = 0
    if lab_cols["susceptibility"]:
        sus_rows = int(
            lab_df[lab_cols["susceptibility"]]
            .dropna()
            .astype(str)
            .str.contains(_SUS_VALUE_RE)
            .sum()
        )

    inter = 0
    if lab_cols["id"] and diag_cols["id"]:
        inter = len(set(lab_df[lab_cols["id"]].dropna()) & set(diag_df[diag_cols["id"]].dropna()))

    return PrepPreview(
        lab_columns=lab_cols,
        diag_columns=diag_cols,
        lab_rows=len(lab_df),
        diag_rows=len(diag_df),
        patients_intersection=inter,
        diagnosis_terms=top_terms,
        susceptibility_rows=sus_rows,
        suggested={
            "value_column": value_col or "归一化值",
            "outcome_scope": "any",
            "index_diagnosis": "first",
            "window_days": 30,
            "value_strategy": "latest",
            "exclude_susceptibility": True,
            "clip_quantile": 0.99,
            "top_n_items": 200,
        },
    )


# ---------- 转换（apply） ----------


def prepare(lab_df: pd.DataFrame, diag_df: pd.DataFrame, d: PrepDecisions) -> PrepResult:
    summary: dict[str, Any] = {"lab_rows_in": len(lab_df), "diag_rows_in": len(diag_df)}

    # 1. 列定位
    id_l = _find_col(lab_df, _ID_COLS)
    item_c = _find_col(lab_df, _ITEM_COLS)
    date_l = _find_col(lab_df, _LAB_DATE_COLS)
    spec_c = _find_col(lab_df, _SPECIMEN_COLS)
    sus_c = _find_col(lab_df, _SUS_COLS)
    if not id_l or not item_c:
        raise ValueError("长表缺少 患者ID/检验名称 列，无法透视")
    if d.value_column not in lab_df.columns:
        raise ValueError(f"缺少取值列：{d.value_column}（可在决策中改用其他列）")
    id_d = _find_col(diag_df, _ID_COLS)
    ddate = _find_col(diag_df, _DIAG_DATE_COLS)
    dtext = _find_col(diag_df, _DIAG_TEXT_COLS)
    if not id_d or not ddate or not dtext:
        raise ValueError("诊断表缺少 患者ID/诊断日期/诊断 列")

    terms = tuple(_norm_term(t) for t in d.outcome_terms if _norm_term(t))
    if not terms:
        raise ValueError("结局定义为空：请至少选择一个诊断词条")

    # 2. 诊断表 → 患者框架（索引诊断 + label）
    diag = diag_df.copy()
    diag["_date"] = pd.to_datetime(diag[ddate], errors="coerce")
    diag["_norm"] = diag[dtext].map(_norm_text)
    diag["_hit"] = diag["_norm"].map(lambda t: any(term in t for term in terms))
    diag = diag.dropna(subset=["_date"]).sort_values("_date")
    pick_last = d.index_diagnosis == "last"
    idx_rows = (
        diag.groupby(id_d, as_index=False).tail(1)
        if pick_last
        else diag.groupby(id_d, as_index=False).head(1)
    )
    patients = idx_rows[[id_d, "_date", "_hit"]].rename(
        columns={id_d: id_l, "_date": "_idx_date", "_hit": "_idx_hit"}
    )
    if d.outcome_scope == "any":
        hit_any = diag.groupby(id_d)["_hit"].any().rename("_any_hit").reset_index()
        patients = patients.merge(hit_any, left_on=id_l, right_on=id_d, how="left")
        if id_d != id_l:
            patients = patients.drop(columns=[id_d])
        patients["label"] = patients["_any_hit"].fillna(False).astype(int)
    else:
        patients["label"] = patients["_idx_hit"].astype(int)
    for extra, cands in (("年龄", _AGE_COLS), ("性别", _SEX_COLS)):
        col = _find_col(diag_df, cands)
        if col:
            vals = idx_rows[[id_d, col]].rename(columns={id_d: id_l, col: extra})
            patients = patients.merge(vals, on=id_l, how="left")
    patients = patients.drop(columns=["_idx_hit", "_any_hit"], errors="ignore")
    summary["patients"] = len(patients)
    summary["label_positive"] = int(patients["label"].sum())

    # 3. 长表清洗
    lab = lab_df.copy()
    if sus_c and d.exclude_susceptibility:
        mask = lab[sus_c].fillna("").astype(str).str.contains(_SUS_VALUE_RE)
        summary["susceptibility_removed"] = int(mask.sum())
        lab = lab[~mask]
    else:
        summary["susceptibility_removed"] = 0
    lab["_value"] = pd.to_numeric(lab[d.value_column], errors="coerce")
    lab = lab.dropna(subset=["_value"])
    summary["lab_rows_value_ok"] = len(lab)
    lab["_date"] = pd.to_datetime(lab[date_l], errors="coerce") if date_l else pd.NaT
    n_nat = int(lab["_date"].isna().sum())
    if n_nat:
        summary["lab_rows_bad_date_dropped"] = n_nat
        lab = lab.dropna(subset=["_date"])

    # 多标本后缀（映射在日期过滤前的全量清洗表上计算，保证 schema 稳定）
    if spec_c:
        n_spec = lab.groupby(item_c)[spec_c].nunique()
        multi = set(n_spec[n_spec > 1].index)
        lab["_feat"] = [
            f"{it}_{sp}" if it in multi else str(it)
            for it, sp in zip(lab[item_c], lab[spec_c], strict=True)
        ]
    else:
        lab["_feat"] = lab[item_c].astype(str)

    # 4. 按项目 winsorize（治理极端脏值）
    summary["clipped_rows"] = 0
    if 0 < d.clip_quantile < 1 and len(lab):
        grp = lab.groupby("_feat")["_value"]
        lo = grp.transform(lambda x: x.quantile(1 - d.clip_quantile))
        hi = grp.transform(lambda x: x.quantile(d.clip_quantile))
        out = (lab["_value"] < lo) | (lab["_value"] > hi)
        summary["clipped_rows"] = int(out.sum())
        lab["_value"] = lab["_value"].clip(lo, hi)

    # 5. TopN 特征项目
    freq = lab["_feat"].value_counts()
    keep_feats = list(freq.head(d.top_n_items).index)
    lab = lab[lab["_feat"].isin(keep_feats)]
    summary["features"] = len(keep_feats)

    # 6. 防泄漏时间窗（硬规则：化验日期 ≤ 索引诊断日期）
    lab = lab.merge(patients[[id_l, "_idx_date"]], on=id_l, how="inner")
    before = len(lab)
    lab = lab[lab["_date"] <= lab["_idx_date"]]
    summary["leakage_removed"] = before - len(lab)
    if d.window_days > 0:
        before = len(lab)
        cutoff = lab["_idx_date"] - pd.Timedelta(days=d.window_days)
        lab = lab[lab["_date"] >= cutoff]
        summary["outside_window_removed"] = before - len(lab)

    # 7. 透视（schema 固定为 keep_feats，窗内无数据的项目列补 NaN）
    if len(lab):
        if d.value_strategy == "mean":
            w = lab.groupby([id_l, "_feat"])["_value"].mean().unstack("_feat")
        else:  # latest
            w = lab.sort_values("_date").groupby([id_l, "_feat"])["_value"].last().unstack("_feat")
        w = w.reindex(columns=keep_feats)
    else:
        w = pd.DataFrame(columns=pd.Index(keep_feats)).rename_axis(id_l)
    w.columns = [str(c) for c in w.columns]

    # 8. 合并产出
    wide = patients.merge(w.reset_index(), on=id_l, how="left").drop(columns=["_idx_date"])
    feat_cols = [c for c in wide.columns if c in keep_feats]
    ordered = [id_l] + [c for c in ("年龄", "性别") if c in wide.columns] + feat_cols + ["label"]
    wide = wide[ordered]
    summary["wide_rows"] = len(wide)
    summary["wide_cols"] = len(wide.columns)
    return PrepResult(wide=wide, summary=summary)
