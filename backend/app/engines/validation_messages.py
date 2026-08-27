"""
优化的验证规则提示信息

提供用户友好的错误提示和操作步骤，替代技术术语。
"""

from typing import Dict, Any


def get_optimized_suggestion(rule_id: str, context: Dict[str, Any] = None) -> str:
    """
    获取优化的提示信息
    
    Args:
        rule_id: 规则 ID（如 RV801）
        context: 上下文信息（如列名、数值等）
        
    Returns:
        优化的提示文本
    """
    context = context or {}
    
    suggestions = {
        "RV001": _rv001_encoding_error,
        "RV002": _rv002_empty_data,
        "RV003": _rv003_duplicate_columns,
        "RV201": _rv201_missing_values,
        "RV301": _rv301_invalid_values,
        "RV401": _rv401_date_format,
        "RV501": _rv501_outliers,
        "RV502": _rv502_clinical_range,
        "RV601": _rv601_high_cardinality,
        "RV701": _rv701_target_missing,
        "RV702": _rv702_missing_key_fields,
        "RV703": _rv703_class_imbalance,
        "RV704": _rv704_duplicate_rows,
        "RV705": _rv705_duplicate_patients,
        "RV801": _rv801_long_table,
        "RV802": _rv802_susceptibility,
        "RV803": _rv803_mixed_units,
        "RV804": _rv804_extreme_values,
    }
    
    func = suggestions.get(rule_id)
    if func:
        return func(context)
    
    return "请参考平台文档修复此问题。"


def _rv001_encoding_error(ctx: Dict[str, Any]) -> str:
    encoding_hint = ctx.get("encoding_hint", "GBK")
    return f"""❌ 文件编码错误，无法读取

可能原因：
- 文件使用了 {encoding_hint} 编码（常见于 Excel 导出）
- 文件格式损坏

解决方法：
方法 1：使用 Excel 重新保存
  1. 用 Excel 打开文件
  2. 点击「文件」→「另存为」
  3. 选择「CSV UTF-8（逗号分隔）」格式
  4. 保存后重新上传

方法 2：使用记事本转换编码
  1. 用记事本打开 CSV 文件
  2. 点击「文件」→「另存为」
  3. 编码选择「UTF-8」
  4. 保存后重新上传
"""


def _rv002_empty_data(ctx: Dict[str, Any]) -> str:
    return """❌ 文件中没有数据

可能原因：
- 文件只有表头，没有数据行
- 文件格式错误

解决方法：
1. 用 Excel 打开文件，检查是否有数据
2. 确保至少有 1 行数据（不含表头）
3. 重新保存后上传
"""


def _rv003_duplicate_columns(ctx: Dict[str, Any]) -> str:
    duplicates = ctx.get("duplicates", [])
    dup_text = "、".join(f"「{d}」" for d in duplicates[:3])
    
    return f"""❌ 检测到重复的列名

重复的列：{dup_text}{"等" if len(duplicates) > 3 else ""}

Excel 导出时可能自动添加了 .1, .2 后缀

解决方法：
1. 在 Excel 中检查表头（第一行）
2. 将重复的列重命名：
   - 「血压」→「收缩压」
   - 「血压.1」→「舒张压」
3. 保存后重新上传
"""


def _rv201_missing_values(ctx: Dict[str, Any]) -> str:
    column = ctx.get("column", "")
    missing_rate = ctx.get("missing_rate", 0)
    severity = ctx.get("severity", "warning")
    
    if severity == "blocker":
        threshold_text = "超过 50%"
        impact = "无法进行有效分析"
    else:
        threshold_text = "20%-50%"
        impact = "可能影响分析质量"
    
    return f"""⚠️ 列「{column}」缺失值过多（{missing_rate*100:.1f}%）

缺失比例：{threshold_text}
影响：{impact}

解决方法：
方法 1：删除该列（如果不重要）
  ✅ 一键操作：点击下方「删除列」按钮

方法 2：填充缺失值
  ✅ 一键操作：点击下方「插补缺失值」按钮
  - 数值列：用中位数填充
  - 分类列：用众数填充

方法 3：手动补充数据
  1. 导出数据
  2. 在 Excel 中补充缺失的值
  3. 重新上传
"""


def _rv301_invalid_values(ctx: Dict[str, Any]) -> str:
    column = ctx.get("column", "")
    invalid_count = ctx.get("invalid_count", 0)
    
    return f"""⚠️ 列「{column}」包含非法值（{invalid_count} 个）

非法值示例：空格、特殊符号、文本（如"未测"）

影响：这些值会被忽略或导致计算错误

解决方法：
✅ 一键操作：点击下方「非法值→缺失」按钮
  - 将非法值标记为缺失，后续可选择插补

手动修复：
  1. 用 Excel 打开数据
  2. 找到列「{column}」
  3. 替换非法值（如"未测"→空白，或填入实际数值）
  4. 保存后重新上传
"""


def _rv401_date_format(ctx: Dict[str, Any]) -> str:
    column = ctx.get("column", "")
    
    return f"""ℹ️ 列「{column}」日期格式不一致

平台将自动统一为 YYYY-MM-DD 格式

支持的格式：
- 2024-01-15
- 2024/01/15
- 01/15/2024
- 2024年1月15日

无需操作，继续即可。
"""


def _rv501_outliers(ctx: Dict[str, Any]) -> str:
    column = ctx.get("column", "")
    outlier_count = ctx.get("outlier_count", 0)
    
    return f"""⚠️ 列「{column}」检测到异常值（{outlier_count} 个）

异常值：远离正常范围的极端数值（可能是录入错误）

影响：可能影响模型性能

解决方法：
✅ 一键操作：点击下方「异常值截尾」按钮
  - 将极端值截断到合理范围（保留 99% 数据范围）

手动检查：
  1. 导出数据
  2. 在 Excel 中排序，查看最大/最小值
  3. 核对是否为录入错误
  4. 修正后重新上传
"""


def _rv502_clinical_range(ctx: Dict[str, Any]) -> str:
    column = ctx.get("column", "")
    unreasonable_count = ctx.get("unreasonable_count", 0)
    min_val = ctx.get("min_val")
    max_val = ctx.get("max_val")
    expected_range = ctx.get("expected_range", "")
    
    return f"""⚠️ 列「{column}」存在临床不合理值（{unreasonable_count} 个）

实际范围：{min_val} ~ {max_val}
正常范围：{expected_range}

可能原因：
- 单位不对（如用 mg/dL 但应该是 mmol/L）
- 录入错误

解决方法：
1. 检查单位是否正确
2. 如果单位不对，统一单位后重新上传
3. 如果是录入错误，用 Excel 修正后重新上传
"""


def _rv601_high_cardinality(ctx: Dict[str, Any]) -> str:
    column = ctx.get("column", "")
    unique_count = ctx.get("unique_count", 0)
    
    return f"""⚠️ 列「{column}」类别过多（{unique_count} 个不同值）

影响：类别过多会导致模型训练困难

常见原因：
- 这可能是 ID 列（如患者编号、病历号）
- 或者是自由文本（如备注、地址）

解决方法：
方法 1：如果是 ID 列
  ✅ 一键操作：点击下方「删除列」按钮

方法 2：如果需要保留
  - 考虑合并相似类别（如地区：北京市朝阳区 → 北京）
  - 或只保留高频类别（Top 10）
"""


def _rv701_target_missing(ctx: Dict[str, Any]) -> str:
    return """❌ 缺少目标变量（要预测的结果列）

平台需要知道您想预测什么结果才能开始分析

示例：
- 预测风险：需要「是否发病」列（0=未发病，1=发病）
- 预测评分：需要「疾病评分」列（数值）
- 生存分析：需要「是否死亡」和「随访时间」两列

解决方法：
方法 1：手动补充
  1. 在 Excel 中添加一列作为结果
  2. 填入数据（0/1 或数值）
  3. 保存后重新上传

方法 2：在下一步手动选择
  - 如果数据中已有结果列但未被识别
  - 在下一步的「列画像」中，将对应列标记为「目标」
"""


def _rv702_missing_key_fields(ctx: Dict[str, Any]) -> str:
    field_name = ctx.get("field_name", "")
    field_zh = ctx.get("field_zh", "")
    advice = ctx.get("advice", "")
    
    return f"""⚠️ 建议补充「{field_zh}」列

当前缺少：{field_name}
建议：{advice}

这不是强制要求，但补充后分析更完整。

如何补充：
1. 在 Excel 中添加「{field_zh}」列
2. 填入数据
3. 保存后重新上传
"""


def _rv703_class_imbalance(ctx: Dict[str, Any]) -> str:
    minority_ratio = ctx.get("minority_ratio", 0)
    
    return f"""⚠️ 目标变量类别不平衡（少数类占比 {minority_ratio*100:.1f}%）

影响：模型可能倾向于预测多数类

示例：
- 100 个样本中，只有 3 个是阳性（3%）
- 模型可能全部预测为阴性（准确率 97%，但没有意义）

解决方法（无需操作，平台会自动处理）：
✅ 平台将自动：
  - 使用类别权重平衡
  - 采用 PR-AUC 而非准确率评估
  - 推荐支持不平衡数据的模型

建议：
- 如果可能，补充更多少数类样本
- 或考虑使用采样方法（SMOTE）
"""


def _rv704_duplicate_rows(ctx: Dict[str, Any]) -> str:
    duplicate_count = ctx.get("duplicate_count", 0)
    
    return f"""⚠️ 检测到完全重复的行（{duplicate_count} 行）

可能原因：
- 数据导出时重复
- Excel 复制粘贴时重复

影响：重复数据会干扰分析结果

解决方法：
✅ 一键操作：点击下方「删除重复行」按钮
  - 自动保留第一次出现的行，删除重复

手动检查：
  1. 在 Excel 中选中数据
  2. 点击「数据」→「删除重复项」
  3. 保存后重新上传
"""


def _rv705_duplicate_patients(ctx: Dict[str, Any]) -> str:
    suspect_count = ctx.get("suspect_count", 0)
    id_column = ctx.get("id_column", "")
    
    return f"""ℹ️ 疑似同一患者的多次记录（{suspect_count} 组）

检测依据：列「{id_column}」有重复值

可能情况：
1. 同一患者的多次就诊（正常）
2. 数据录入重复（需要删除）

如何判断：
✅ 情况 1（多次就诊）：
  - 如果有「就诊日期」列，日期不同 → 正常
  - 需要决定：用首次就诊 or 最后就诊 or 每次单独分析

❌ 情况 2（录入重复）：
  - 如果所有信息完全相同 → 删除重复

建议：
- 检查数据，确认是哪种情况
- 如果是重复录入，使用「删除重复行」
"""


def _rv801_long_table(ctx: Dict[str, Any]) -> str:
    item_column = ctx.get("item_column", "")
    value_column = ctx.get("value_column", "")
    
    return f"""❌ 检测到长表格式（每个检验项目占一行）

当前格式：
| 患者ID | {item_column} | {value_column} |
|--------|---------------|----------------|
| P001   | 血钾          | 3.5            |
| P001   | 血钠          | 140            |
| P002   | 血钾          | 4.2            |

平台需要宽表格式（每行 = 1 个患者）：
| 患者ID | 血钾 | 血钠 |
|--------|------|------|
| P001   | 3.5  | 140  |
| P002   | 4.2  | 138  |

解决方法：
方法 1：Excel 数据透视表
  1. 选中数据
  2. 点击「插入」→「数据透视表」
  3. 拖拽设置：
     - 行：患者ID
     - 列：{item_column}
     - 值：{value_column}
  4. 导出透视表结果，重新上传

方法 2：使用平台的「长表转宽表」工具
  ✅ 即将上线，敬请期待

方法 3：Python pandas（适合程序员）
  ```python
  df_wide = df.pivot(
      index='患者ID',
      columns='{item_column}',
      values='{value_column}'
  )
  ```
"""


def _rv802_susceptibility(ctx: Dict[str, Any]) -> str:
    sus_column = ctx.get("sus_column", "")
    sus_count = ctx.get("sus_count", 0)
    
    return f"""⚠️ 检测到药敏试验记录（{sus_count} 行）

列「{sus_column}」包含：敏感、耐药、中介

问题：
- 药敏结果不是检验指标
- 直接入模会干扰分析

解决方法：
方法 1：删除药敏记录
  ✅ 一键操作：点击下方「删除匹配行」按钮

方法 2：整理为特征
  - 将药敏结果整理为「耐药史」
  - 例如：「耐青霉素」（0=否，1=是）
"""


def _rv803_mixed_units(ctx: Dict[str, Any]) -> str:
    examples = ctx.get("examples", [])
    example_text = "、".join(f"「{e}」" for e in examples[:3])
    
    return f"""⚠️ 同一检验项目存在多种单位

示例：{example_text}

问题：
- 单位不统一导致数值无法比较
- 例如：血糖 5.5 mmol/L ≈ 99 mg/dL

解决方法：
✅ 一键操作：点击下方「单位标准化」按钮
  - 自动转换为统一单位

手动修复：
  1. 在 Excel 中统一单位
  2. 使用公式转换（如 mmol/L × 18 = mg/dL）
  3. 保存后重新上传
"""


def _rv804_extreme_values(ctx: Dict[str, Any]) -> str:
    column = ctx.get("column", "")
    extreme = ctx.get("extreme", 0)
    
    return f"""⚠️ 列「{column}」存在极端值（绝对值达 {extreme:g}）

可能原因：
- 单位错误（如用 g 但应该是 mg）
- 录入错误（多打了几个 0）

解决方法：
1. 检查单位是否正确
2. 查看最大/最小值，判断是否合理
3. 如果是错误，在 Excel 中修正
4. 或使用「异常值截尾」功能
"""
