"""图表 PNG 字体规范（docs/10 §2.1）：CJK 首选 Noto Sans CJK SC。

用户数据集列名可为中文（特征重要性 Y 轴等），缺字方块曾导致乱码；
容器已打包 fonts-noto-cjk，matplotlib rcParams 在 chart_png 模块导入时设置。
"""

import matplotlib
from app.engines.reporting.chart_png import chart_to_png


def test_cjk_font_configured() -> None:
    assert matplotlib.rcParams["font.sans-serif"][0] == "Noto Sans CJK SC"
    assert matplotlib.rcParams["axes.unicode_minus"] is False  # 负号走 ASCII


def test_chinese_feature_names_render() -> None:
    """中文特征名的 feature_importance 渲染不中断（字体缺失时降级不报错）。"""
    chart = {
        "kind": "feature_importance",
        "data": {
            "features": ["年龄", "收缩压", "空腹血糖"],
            "series": [{"model_key": "rf", "values": [0.9, 0.7, 0.4]}],
        },
    }
    assert chart_to_png(chart) is not None
