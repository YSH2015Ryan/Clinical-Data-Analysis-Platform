"""HTML 渲染（docs/10 §3 渲染管线；T7.2 模板 + T7.3 装配）。

单一事实源：先渲染 HTML，PDF/其他格式由其派生。
模板版本化：template_key + version 存入 Report，可复现旧报告样式。
"""

import math
from pathlib import Path
from typing import Any

import jinja2

_TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_KEY = "clinical_report_zh"
TEMPLATE_VERSION = "1.1.1"


def _fmt_num(value: Any, spec: str = ".3g") -> str:
    """数值渲染守卫（T6.15①）：None/nan/inf → '—'；否则按 spec 格式化。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(f) or math.isinf(f):
        return "—"
    return ("%" + spec) % f


_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    autoescape=True,
    keep_trailing_newline=True,
)
_env.filters["fmt_num"] = _fmt_num


def render_html(
    context: dict[str, Any], template_key: str = TEMPLATE_KEY, *, collapsible: bool = False
) -> str:
    """ReportContext → HTML 字符串；未知模板键抛 jinja2.TemplateNotFound。

    collapsible=True 时重点表以 <details> 默认折叠（docs/10 §2.2，仅 HTML 产物；
    PDF/Word/Markdown 派生物一律 False 保持全展开）。
    """
    return _env.get_template(f"{template_key}.html.j2").render(collapsible=collapsible, **context)
