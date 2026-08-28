"""模型失败原因分类（T6.5）：裸异常 → 分类 + 用户可读提示 + 建议动作。

纯函数，不依赖 celery/billiard（分层纪律）：软超时按异常类名鸭子识别
（billiard.exceptions.SoftTimeLimitExceeded）。
"""

_CATEGORY_LABELS = {
    "timeout": "超时",
    "memory": "内存不足",
    "convergence": "未收敛",
    "data": "数据不适配",
    "unknown": "未知错误",
}

_MESSAGES = {
    "timeout": (
        "模型训练超过时间限制被中止",
        "减少样本量或特征数、降低模型复杂度（如减少树的数量/深度）后重跑该模型；"
        "或改用更轻量的模型（如逻辑回归/LASSO）。",
    ),
    "memory": (
        "模型训练因内存不足被中止",
        "减少特征数（预处理阶段开启特征选择）、降低模型复杂度；"
        "平台已对大样本自动分层采样，仍失败时请换更轻量的模型。",
    ),
    "convergence": (
        "模型迭代未收敛",
        "检查特征尺度（建议预处理开启标准化）、增大最大迭代次数或调整正则化强度后重跑。",
    ),
    "data": (
        "数据不适配该模型",
        "根据原始错误检查结局列类型、缺失值、常量列或类别不平衡；必要时调整预处理配置后重跑。",
    ),
    "unknown": (
        "模型训练失败",
        "查看原始错误信息定位原因；若持续失败请联系平台管理员。",
    ),
}


def classify_model_failure(exc: BaseException) -> dict[str, str]:
    """异常 → {category, category_label, message, suggestion}。

    分类规则（按优先级）：
    - timeout：软/硬时间限制（类名 SoftTimeLimitExceeded 或文本含 time limit）；
    - memory：MemoryError 或文本含 memory/allocate；
    - convergence：文本含 converge/convergence；
    - data：ValueError 等数据形态错误（NaN/无穷/类型不符/常量列）；
    - unknown：其余。
    """
    text = str(exc).lower()
    mro_names = {cls.__name__ for cls in type(exc).__mro__}
    if "SoftTimeLimitExceeded" in mro_names or "time limit" in text or "timeout" in text:
        category = "timeout"
    elif isinstance(exc, MemoryError) or "memory" in text or "unable to allocate" in text:
        category = "memory"
    elif "converge" in text or "convergence" in text:
        category = "convergence"
    elif isinstance(exc, ValueError | TypeError) or "nan" in text or "infinite" in text:
        category = "data"
    else:
        category = "unknown"
    message, suggestion = _MESSAGES[category]
    return {
        "category": category,
        "category_label": _CATEGORY_LABELS[category],
        "message": message,
        "suggestion": suggestion,
    }


def format_model_failure(exc: BaseException) -> str:
    """一行式用户可读失败原因（落 ModelResult.error，前端逐模型展示）。"""
    info = classify_model_failure(exc)
    raw = str(exc).strip() or type(exc).__name__
    return (
        f"[{info['category_label']}] {info['message']}。建议：{info['suggestion']}"
        f"（原始错误：{raw}）"
    )
