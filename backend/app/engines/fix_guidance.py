"""结构化修复指引引擎（P2-3）：问题 → 影响 → 修法闭环。

每条校验 Issue 附带结构化指引：修法按优先级排序，可安全自动化的附一键修复动作
（与 quickfix 引擎动作契约一致），不可逆/需人工判断的只给手动步骤（action=None）。
纯函数、无 I/O、确定性；分层纪律：engines 不依赖 fastapi/celery/sqlalchemy。
"""

from typing import Any

# quickfix 动作的风险说明（与前端 FIX_RISK 同源；一键动作必须附风险）
_RISK: dict[str, str] = {
    "drop_column": "该列将从新版本中彻底移除，其中的数据在新版本不可恢复（适用于确认无用的列）。",
    "drop_duplicates": "完全重复的数据行将被删除，仅保留一份；若重复本身是真实记录，会造成样本损失。",
    "to_missing": "无法识别的取值将被置为缺失，原取值在新版本不可恢复。",
    "winsorize_outliers": "异常值将被截断到分位数边界，极端值会被修改但不会被删除。",
    "impute_missing": "缺失值将被自动填充（数值列用中位数，分类列用众数），原始缺失状态不可恢复。",
    "drop_rows_with_pattern": "匹配指定模式的行将被删除，新版本不可恢复。",
}


def _action(action_type: str, column: str | None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": action_type, "column": column, "params": params or {}}


def _method(
    label: str,
    description: str,
    action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "label": label,
        "description": description,
        "action": action,
        "risk": _RISK[action["type"]] if action else None,
    }


def _manual(label: str, description: str) -> dict[str, Any]:
    return _method(label, description, None)


def fix_guidance_for(issue: Any) -> dict[str, Any]:
    """按规则生成结构化修复指引（issue 为 engines.validation Issue 或同形对象）。"""
    rid: str = issue.rule_id
    col: str | None = issue.column
    sev: str = issue.severity
    n = issue.affected_rows or 0

    if rid == "RV201":
        rate_hint = f"该列缺失 {n} 行"
        if sev == "blocker":
            return {
                "problem": f"列「{col}」缺失率超过 50%（{rate_hint}），信息损失严重。",
                "impact": "缺失过半的列插补后分布严重失真，纳入建模会引入系统性偏倚，统计结论不可靠。",
                "methods": [
                    _method(
                        "删除该列（推荐）",
                        "缺失过半的列保留价值低，删除后用其余特征建模更稳健。",
                        _action("drop_column", col),
                    ),
                    _manual(
                        "补齐源数据后重新上传",
                        "回到临床系统/Excel 补齐该列缺失值，重新上传（最可靠，保留真实信息）。",
                    ),
                ],
            }
        return {
            "problem": f"列「{col}」存在缺失（{rate_hint}）。",
            "impact": "含缺失的行在多数建模流程中被剔除，样本量减少、可能引入选择偏倚；插补不当会压缩方差。",
            "methods": [
                _method(
                    "一键插补（数值列中位数 / 分类列众数）",
                    "缺失率中等时插补是常规做法；插补值是估计值，报告中应说明插补策略。",
                    _action("impute_missing", col, {"strategy": "auto"}),
                ),
                _manual(
                    "补齐源数据后重新上传",
                    "若能从病历/检验系统补回真实值，优先补齐后重新上传。",
                ),
                _method(
                    "删除该列",
                    "若该列对研究问题不重要，可直接删除。",
                    _action("drop_column", col),
                ),
            ],
        }

    if rid == "RV301":
        return {
            "problem": f"列「{col}」整体为数值意图，但混入 {n} 个非数值（如「未知」「-」）。",
            "impact": "非数值会使整列被识别为文本，无法参与统计计算与建模。",
            "methods": [
                _method(
                    "一键转为缺失",
                    "将无法识别的取值置为缺失，之后可按缺失流程插补；列恢复为数值型。",
                    _action("to_missing", col),
                ),
                _manual("修正源数据后重新上传", "若非法值是录入错误（如单位混入），请在 Excel 修正后重新上传。"),
            ],
        }

    if rid == "RV401":
        if col is None:
            return {
                "problem": f"数据包含 {n} 行完全重复的记录。",
                "impact": "重复行会让同一患者被多次计数，高估样本量并低估置信区间宽度。",
                "methods": [
                    _method("一键去重", "仅保留每组完全重复记录中的一份。", _action("drop_duplicates", None)),
                    _manual("核对后保留", "若重复是真实的多次就诊记录，应保留并考虑改用重复测量模型。"),
                ],
            }
        return {
            "problem": f"按标识列「{col}」检测到 {n} 条疑似同一患者记录。",
            "impact": "同一患者多条记录会破坏独立性假设；也可能是正常的随访/复诊。",
            "methods": [
                _manual(
                    "人工核对",
                    "确认是重复录入（删除）还是多次就诊（保留并在分析中注明聚类/混合效应）。",
                ),
            ],
        }

    if rid in ("RV501", "RV804"):
        return {
            "problem": f"列「{col}」存在 {n} 个统计异常值/极端值。",
            "impact": "极端值会显著拉偏均值、回归系数与变量重要性；但也可能是真实重症患者，直接删除会丢失信息。",
            "methods": [
                _method(
                    "一键截尾（Winsorize）",
                    "把超出分位边界的取值收回到边界，保留样本但限制其影响，是临床数据的常规处理。",
                    _action("winsorize_outliers", col),
                ),
                _manual(
                    "人工核对原始值",
                    "核对是否为录入/单位错误（如多写一个 0）；确认错误请在 Excel 修正后重新上传。",
                ),
            ],
        }

    if rid == "RV502":
        return {
            "problem": f"列「{col}」有 {n} 个值超出临床合理范围。",
            "impact": "超范围取值几乎必然是单位错误或录入错误，直接建模会产生错误结论。",
            "methods": [
                _manual("核对单位", "常见原因是单位不一致（如 mg/dL 与 mmol/L），换算后重新上传。"),
                _manual("修正录入错误", "对照原始病历修正极端值后重新上传。"),
            ],
        }

    if rid == "RV601":
        return {
            "problem": f"列「{col}」唯一值过多，疑似 ID 列或自由文本。",
            "impact": "高基数列无法作为分类特征（每个类别样本过少），若为 ID 还会造成数据泄漏。",
            "methods": [
                _method("删除该列", "确认是 ID/姓名等标识列时删除，避免泄漏与过拟合。", _action("drop_column", col)),
                _manual("合并类别", "若是有意义的分类（如诊断名称），在 Excel 归并相似类别后重新上传。"),
            ],
        }

    if rid == "RV701":
        return {
            "problem": "结局类别不平衡（少数类占比过低）。",
            "impact": "模型会偏向多数类，准确率虚高而少数类召回很差；需用 PR-AUC/类别权重评估。",
            "methods": [
                _manual("无需修复", "平台建模时自动使用类别权重与 PR-AUC 指标；报告中应说明类别比例。"),
                _manual("扩充少数类样本", "若少数类样本过少（EPV 不足），优先补充病例。"),
            ],
        }

    if rid == "RV801":
        return {
            "problem": "检测到长表结构（一行一条检验记录，而非一行一个患者）。",
            "impact": "建模要求宽表（一行一个患者、一列一个变量）；长表直接建模会把同一患者拆成多条样本。",
            "methods": [
                _manual("用数据准备功能转宽表", "使用平台「数据准备」向导（长表+诊断表 → 宽表）完成转换。"),
                _manual("Excel 数据透视表", "自行用数据透视表转为宽表后重新上传。"),
            ],
        }

    if rid == "RV802":
        return {
            "problem": f"检测到 {n} 行疑似药敏试验记录（敏感/耐药/中介）。",
            "impact": "药敏结果不是数值化验结果，混入会污染检验指标的分布与建模。",
            "methods": [
                _method(
                    "一键删除药敏行",
                    "删除「敏感/耐药/中介」匹配行；若研究主题本身是药敏请勿使用。",
                    _action("drop_rows_with_pattern", col, {"pattern": "敏感|耐药|中介"}),
                ),
                _manual("拆分数据集", "若药敏信息有研究价值，拆分为独立数据集另行分析。"),
            ],
        }

    if rid == "RV803":
        return {
            "problem": "同一检验项目存在多种单位。",
            "impact": "不同单位的数值直接混合会让分布与统计量完全失真。",
            "methods": [
                _manual("统一单位后重新上传", "在 Excel 用公式换算（如 mmol/L × 18 = mg/dL）后重新上传。"),
            ],
        }

    if rid == "RV101":
        return {
            "problem": "未识别到结局（目标）变量列。",
            "impact": "没有结局变量无法做预测建模；只能做探索性分析。",
            "methods": [
                _manual("在列画像中标记语义", "若已有结局列但未识别，在「列画像」中将其标记为 Label/Event。"),
                _manual("补充结局列后重新上传", "在 Excel 中添加结局/事件列后重新上传。"),
            ],
        }

    if rid == "RV102":
        return {
            "problem": "缺少推荐字段（如年龄、性别）。",
            "impact": "缺少人口学字段会限制分层分析与基线表（Table 1）的完整性，不影响建模主流程。",
            "methods": [
                _manual("补充字段后重新上传", "非强制；补齐后可支持更完整的科研报告。"),
            ],
        }

    if rid == "RV001":
        return {
            "problem": "文件无法解析（编码或格式错误）。",
            "impact": "数据完全无法读取，后续任何分析都无法进行。",
            "methods": [
                _manual("另存为 UTF-8 CSV", "用 Excel「另存为 → CSV UTF-8」或记事本「另存为 → UTF-8」后重新上传。"),
            ],
        }

    if rid == "RV003":
        return {
            "problem": "存在重复列名。",
            "impact": "重复列名会让数据对齐出错（后列覆盖前列），分析结果不可信。",
            "methods": [
                _manual("重命名重复列", "在 Excel 中将重复列改名（如「血压」→「收缩压」）后重新上传。"),
            ],
        }

    # 未知规则回退：只给手动指引，绝不凭空造动作
    return {
        "problem": issue.message or f"规则 {rid} 报告的问题。",
        "impact": "该问题需人工判断其对分析的影响。",
        "methods": [_manual("按建议手动处理", "参考「建议」列的指引修正数据后重新上传。")],
    }
