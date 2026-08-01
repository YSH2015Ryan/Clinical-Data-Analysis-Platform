"""HTML → PDF（docs/10 §3 渲染管线：HTML 主产物派生 PDF）。

WeasyPrint 依赖系统 pango/gdk-pixbuf（Dockerfile base 阶段安装）；
中文字体 Noto Sans CJK 打包进镜像（docs/10 §5 无缺字），模板 CSS
font-family 已声明 "Noto Sans CJK SC"，fontconfig 自动命中。
"""

from typing import cast

import weasyprint


def html_to_pdf(html: str) -> bytes:
    """渲染 HTML 字符串为 PDF 字节（图片已 base64 内联，无外部资源）。"""
    return cast(bytes, weasyprint.HTML(string=html).write_pdf())
