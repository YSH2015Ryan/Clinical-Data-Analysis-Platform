"""
报告增强 - 基线特征表生成（Table 1）

生成论文级别的基线特征表，包括描述统计和分层比较。
"""

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


def generate_baseline_table(
    df: pd.DataFrame,
    continuous_cols: list[str] | None = None,
    categorical_cols: list[str] | None = None,
    stratify_by: str | None = None,
    test_difference: bool = True,
) -> dict[str, Any]:
    """
    生成基线特征表（Table 1）

    Args:
        df: 数据框
        continuous_cols: 连续变量列表（如果为 None，自动检测）
        categorical_cols: 分类变量列表（如果为 None，自动检测）
        stratify_by: 分层变量（如"训练集/测试集"或"阳性/阴性"）
        test_difference: 是否进行统计检验

    Returns:
        {
            "rows": [特征行数据],
            "total_n": 总样本量,
            "strata": 分层信息,
            "note": 说明文本
        }
    """
    if df.empty:
        return {"rows": [], "total_n": 0, "strata": [], "note": "数据为空"}

    # 自动检测列类型
    if continuous_cols is None:
        continuous_cols = _detect_continuous_cols(df)

    if categorical_cols is None:
        categorical_cols = _detect_categorical_cols(df)

    # 移除重叠
    continuous_cols = [c for c in continuous_cols if c in df.columns and c != stratify_by]
    categorical_cols = [c for c in categorical_cols if c in df.columns and c != stratify_by]

    # 构建表格行
    rows = []

    # 总体统计
    total_n = len(df)

    # 分层信息
    strata_info = []
    if stratify_by and stratify_by in df.columns:
        strata_groups = df[stratify_by].unique()
        strata_groups = [g for g in strata_groups if pd.notna(g)]

        for group in strata_groups:
            group_df = df[df[stratify_by] == group]
            strata_info.append({"name": str(group), "n": len(group_df)})
    else:
        strata_info.append({"name": "Total", "n": total_n})

    # 连续变量
    for col in continuous_cols:
        row = _summarize_continuous(df, col, stratify_by, test_difference)
        if row:
            rows.append(row)

    # 分类变量
    for col in categorical_cols:
        category_rows = _summarize_categorical(df, col, stratify_by, test_difference)
        rows.extend(category_rows)

    return {
        "rows": rows,
        "total_n": total_n,
        "strata": strata_info,
        "note": _generate_table_note(test_difference),
    }


def _detect_continuous_cols(df: pd.DataFrame) -> list[str]:
    """自动检测连续变量"""
    continuous = []
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            n_unique = df[col].nunique()
            # 超过10个唯一值视为连续
            if n_unique > 10:
                continuous.append(col)
    return continuous


def _detect_categorical_cols(df: pd.DataFrame) -> list[str]:
    """自动检测分类变量"""
    categorical = []
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_categorical_dtype(df[col]):
            categorical.append(col)
        elif pd.api.types.is_numeric_dtype(df[col]):
            n_unique = df[col].nunique()
            # 少于10个唯一值视为分类
            if 2 <= n_unique <= 10:
                categorical.append(col)
    return categorical


def _summarize_continuous(
    df: pd.DataFrame, col: str, stratify_by: str | None, test_difference: bool
) -> dict[str, Any] | None:
    """
    汇总连续变量

    返回格式：mean ± SD 或 median (IQR)
    """
    values = df[col].dropna()

    if len(values) == 0:
        return None

    # 检查正态性（样本量>20时）
    use_mean = len(values) <= 20 or _is_normal(values)

    row = {
        "variable": col,
        "type": "continuous",
        "format": "mean±sd" if use_mean else "median(iqr)",
    }

    # 总体统计
    if use_mean:
        row["total"] = f"{values.mean():.2f} ± {values.std():.2f}"
    else:
        q1, median, q3 = values.quantile([0.25, 0.5, 0.75])
        row["total"] = f"{median:.2f} ({q1:.2f}, {q3:.2f})"

    # 分层统计
    if stratify_by and stratify_by in df.columns:
        strata_values = []
        strata_labels = []

        for group in df[stratify_by].unique():
            if pd.isna(group):
                continue

            group_values = df[df[stratify_by] == group][col].dropna()
            strata_labels.append(str(group))
            strata_values.append(group_values)

            if len(group_values) == 0:
                row[f"stratum_{group}"] = "—"
            elif use_mean:
                row[f"stratum_{group}"] = f"{group_values.mean():.2f} ± {group_values.std():.2f}"
            else:
                q1, median, q3 = group_values.quantile([0.25, 0.5, 0.75])
                row[f"stratum_{group}"] = f"{median:.2f} ({q1:.2f}, {q3:.2f})"

        # 统计检验
        if test_difference and len(strata_values) >= 2:
            p_value = _test_continuous_difference(strata_values, use_mean)
            row["p_value"] = p_value
            row["p_value_text"] = _format_pvalue(p_value)
        else:
            row["p_value"] = None
            row["p_value_text"] = "—"

    return row


def _summarize_categorical(
    df: pd.DataFrame, col: str, stratify_by: str | None, test_difference: bool
) -> list[dict[str, Any]]:
    """
    汇总分类变量

    返回格式：n (%)，每个类别一行
    """
    rows = []

    # 获取所有类别
    categories = df[col].value_counts().index.tolist()

    # 父行（变量名）
    parent_row = {
        "variable": col,
        "type": "categorical_header",
        "total": "",
        "p_value": None,
        "p_value_text": "",
    }

    if stratify_by and stratify_by in df.columns:
        for group in df[stratify_by].unique():
            if pd.notna(group):
                parent_row[f"stratum_{group}"] = ""

    rows.append(parent_row)

    # 子行（每个类别）
    for category in categories:
        if pd.isna(category):
            continue

        row = {"variable": f"  {category}", "type": "categorical_value", "category": str(category)}

        # 总体统计
        n_total = int((df[col] == category).sum())
        pct_total = n_total / len(df) * 100
        row["total"] = f"{n_total} ({pct_total:.1f}%)"

        # 分层统计
        if stratify_by and stratify_by in df.columns:
            contingency_table = []

            for group in df[stratify_by].unique():
                if pd.isna(group):
                    continue

                group_df = df[df[stratify_by] == group]
                n_group = int((group_df[col] == category).sum())
                pct_group = n_group / len(group_df) * 100 if len(group_df) > 0 else 0
                row[f"stratum_{group}"] = f"{n_group} ({pct_group:.1f}%)"

                # 为列联表准备数据
                contingency_table.append([n_group, len(group_df) - n_group])

            # 统计检验（仅在第一个类别行显示）
            if category == categories[0] and test_difference and len(contingency_table) >= 2:
                p_value = _test_categorical_difference(contingency_table)
                row["p_value"] = p_value
                row["p_value_text"] = _format_pvalue(p_value)
            else:
                row["p_value"] = None
                row["p_value_text"] = ""

        rows.append(row)

    return rows


def _is_normal(values: pd.Series) -> bool:
    """检查正态性（Shapiro-Wilk 检验）"""
    if len(values) < 3 or len(values) > 5000:
        return True  # 样本过小或过大，默认使用均值

    try:
        _, p_value = stats.shapiro(values)
        return p_value > 0.05
    except Exception:
        return True


def _test_continuous_difference(strata_values: list[pd.Series], use_mean: bool) -> float | None:
    """
    检验连续变量的组间差异

    参数版本使用 t 检验或 ANOVA
    非参数版本使用 Mann-Whitney U 或 Kruskal-Wallis
    """
    # 移除空组
    strata_values = [v for v in strata_values if len(v) > 0]

    if len(strata_values) < 2:
        return None

    try:
        if len(strata_values) == 2:
            # 两组比较
            if use_mean:
                # t 检验
                _, p_value = stats.ttest_ind(strata_values[0], strata_values[1])
            else:
                # Mann-Whitney U 检验
                _, p_value = stats.mannwhitneyu(strata_values[0], strata_values[1])
        else:
            # 多组比较
            if use_mean:
                # ANOVA
                _, p_value = stats.f_oneway(*strata_values)
            else:
                # Kruskal-Wallis
                _, p_value = stats.kruskal(*strata_values)

        return float(p_value)
    except Exception:
        return None


def _test_categorical_difference(contingency_table: list[list[int]]) -> float | None:
    """
    检验分类变量的组间差异（χ² 检验或 Fisher 精确检验）
    """
    contingency_array = np.array(contingency_table).T

    if contingency_array.size == 0:
        return None

    try:
        # 样本量较小时使用 Fisher 精确检验
        if contingency_array.shape == (2, 2) and contingency_array.sum() < 30:
            _, p_value = stats.fisher_exact(contingency_array)
        else:
            # χ² 检验
            _, p_value, _, _ = stats.chi2_contingency(contingency_array)

        return float(p_value)
    except Exception:
        return None


def _format_pvalue(p_value: float | None) -> str:
    """格式化 p 值"""
    if p_value is None:
        return "—"

    if p_value < 0.001:
        return "<0.001"
    elif p_value < 0.01:
        return f"{p_value:.3f}"
    else:
        return f"{p_value:.3f}"


def _generate_table_note(test_difference: bool) -> str:
    """生成表格说明"""
    note = "连续变量以 mean ± SD 或 median (Q1, Q3) 表示；分类变量以 n (%) 表示。"

    if test_difference:
        note += (
            " p 值：连续变量使用 t 检验或 Mann-Whitney U 检验；"
            "分类变量使用 χ² 检验或 Fisher 精确检验。"
        )

    return note


def format_baseline_table_html(table_data: dict[str, Any]) -> str:
    """
    将基线表格式化为 HTML

    Args:
        table_data: generate_baseline_table 返回的数据

    Returns:
        HTML 表格字符串
    """
    rows = table_data.get("rows", [])
    strata = table_data.get("strata", [])
    total_n = table_data.get("total_n", 0)

    if not rows:
        return "<p>无基线特征数据</p>"

    # 构建表头
    html = ['<table class="baseline-table">']
    html.append("<thead><tr>")
    html.append("<th>特征</th>")
    html.append(f"<th>总计 (N={total_n})</th>")

    for stratum in strata:
        if stratum["name"] != "Total":
            html.append(f"<th>{stratum['name']} (N={stratum['n']})</th>")

    if len(strata) > 1:
        html.append("<th>p 值</th>")

    html.append("</tr></thead>")

    # 构建表体
    html.append("<tbody>")
    for row in rows:
        if row["type"] == "categorical_header":
            html.append(f"<tr><td><strong>{row['variable']}</strong></td>")
            html.append('<td colspan="100%"></td></tr>')
        else:
            html.append("<tr>")
            html.append(f"<td>{row['variable']}</td>")
            html.append(f"<td>{row.get('total', '—')}</td>")

            for stratum in strata:
                if stratum["name"] != "Total":
                    stratum_key = f"stratum_{stratum['name']}"
                    html.append(f"<td>{row.get(stratum_key, '—')}</td>")

            if len(strata) > 1:
                html.append(f"<td>{row.get('p_value_text', '')}</td>")

            html.append("</tr>")

    html.append("</tbody>")
    html.append("</table>")

    # 添加注释
    note = table_data.get("note", "")
    if note:
        html.append(f'<p class="table-note"><small>{note}</small></p>')

    return "\n".join(html)
