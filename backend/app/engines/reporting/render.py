"""HTML 渲染（docs/10 §3 渲染管线；T7.2 模板 + T7.3 装配）。

单一事实源：先渲染 HTML，PDF/其他格式由其派生。
模板版本化：template_key + version 存入 Report，可复现旧报告样式。
"""

from pathlib import Path
from typing import Any

import jinja2

_TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_KEY = "clinical_report_zh"
TEMPLATE_VERSION = "1.0.0"

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    autoescape=True,
    keep_trailing_newline=True,
)


def render_html(context: dict[str, Any], template_key: str = TEMPLATE_KEY) -> str:
    """ReportContext → HTML 字符串；未知模板键抛 jinja2.TemplateNotFound。"""
    return _env.get_template(f"{template_key}.html.j2").render(**context)
