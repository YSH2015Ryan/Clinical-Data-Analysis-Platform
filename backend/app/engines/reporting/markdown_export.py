"""HTML → Markdown 自研转换（docs/10 §3 渲染管线：HTML 主产物派生 Markdown）。

stdlib html.parser 实现，覆盖报告模板实际用到的标签（h1/h2/p/table/ul/li/
img/code/strong/caption）；图表 base64 不内联（体积），以 alt 占位标注
「见 HTML/PDF 版」。无第三方依赖，避免 pandoc 二进制引入镜像。
"""

from html.parser import HTMLParser

_IMAGE_PLACEHOLDER = "（PNG 图像见 HTML/PDF 版报告）"


class _MdBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip = 0  # <style>/<head> 深度
        self._heading: int | None = None  # 当前标题级别（1/2）
        self._buf: list[str] = []  # 标题/单元格文本缓冲
        self._rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    # ---- 文本收集 ----
    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data.strip())
        elif self._heading is not None:
            self._buf.append(data.strip())
        else:
            text = data.strip()
            if text:
                self._out.append(text)

    # ---- 标签 ----
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("style", "head"):
            self._skip += 1
        elif self._skip:
            return
        elif tag == "h1":
            self._heading, self._buf = 1, []
        elif tag == "h2":
            self._heading, self._buf = 2, []
        elif tag == "p":
            self._out.append("\n")
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "li":
            self._out.append("\n- ")
        elif tag == "caption":
            self._out.append("\n**")
        elif tag == "img":
            alt = next((v for k, v in attrs if k == "alt"), None) or "图表"
            self._out.append(f"\n![{alt}]{_IMAGE_PLACEHOLDER}\n")
        elif tag == "br":
            self._out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "head"):
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in ("h1", "h2") and self._heading is not None:
            text = " ".join(t for t in self._buf if t)
            self._out.append(f"\n{'#' * self._heading} {text}\n")
            self._heading = None
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join(t for t in self._cell if t).replace("|", "\\|"))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._rows.append(self._row)
            self._row = None
        elif tag == "table":
            self._out.append("\n" + self._render_table() + "\n")
            self._rows = []
        elif tag == "caption":
            self._out.append("**\n")

    def _render_table(self) -> str:
        if not self._rows:
            return ""
        width = max(len(r) for r in self._rows)
        rows = [r + [""] * (width - len(r)) for r in self._rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(lines)


def html_to_markdown(html: str) -> str:
    """报告 HTML → Markdown（章节结构完整；图像以占位标注）。"""
    builder = _MdBuilder()
    builder.feed(html)
    builder.close()
    lines = builder._out  # 构建器内部缓冲即产物
    text = " ".join(lines)
    # 折叠多余空白（保留标题/表格/列表换行）
    out: list[str] = []
    for line in text.split("\n"):
        cleaned = " ".join(line.split())
        if cleaned or (out and out[-1]):
            out.append(cleaned)
    return "\n".join(out).strip() + "\n"
