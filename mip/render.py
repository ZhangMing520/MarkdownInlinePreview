"""render.py — Markdown 渲染管线的共享前半段 + minihtml 适配后半段。

编排（见文件底部）：render_raw（引擎 + front matter）两种预览共用；
render_html 在其后加 minihtml 适配，render_body 直接内嵌图片给浏览器用。

minihtml 是 HTML 子集，明确不支持 <table>/<input>/<button>/<del> 等标签，
且没有 width/百分比/flexbox/overflow 滚动（官方 minihtml 文档已核实），
所以适配层做三件事：
  1. 标签转换层：table→等宽字体网格或卡片、input→[x]/[ ]、del/s→line-through（与引擎无关）
  2. 图片 base64 内嵌（仅本地图片同步内嵌；远程 http/https/data 原样保留）
  3. <style> 样式块（DEFAULT_STYLE）+ 按顶层块分片；样式由 preview.py 在
     插入每个 phantom 时前置（phantom 是独立 minihtml 文档，必须各自带样式）

全部是纯函数，可在无 Sublime 环境单测。
"""

import base64
import logging
import os
import re
import unicodedata
from html import escape, unescape
from html.parser import HTMLParser

from .normalize import normalize_html

logger = logging.getLogger("MarkdownInlinePreview")


# ---------------------------------------------------------------------------
# 标签转换层
# ---------------------------------------------------------------------------

_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.S | re.I)
_THEAD_RE = re.compile(r"<thead[^>]*>(.*?)</thead>", re.S | re.I)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t([hd])[^>]*>(.*?)</t\1>", re.S | re.I)
_INNER_TAG_RE = re.compile(r"<[^>]+>")
_INPUT_RE = re.compile(r"<input[^>]*type=[\"']?checkbox[\"']?[^>]*>", re.S | re.I)
_DEL_RE = re.compile(r"<(del|s)(?=[\s>/])[^>]*>(.*?)</\1>", re.S | re.I)
# 宽度不可测的单元格内容：img 按自身尺寸渲染（alt 不计宽），块级标签自带换行，
# 两者都会破坏 nbsp 补齐的列对齐 → 整表放弃网格
_RICH_CELL_RE = re.compile(r"<(img|p|div|ul|ol|li|pre|blockquote)(?=[\s>/])", re.I)

# 网格布局常量：minihtml 没有 width 属性，列对齐只能靠等宽字体 + nbsp 补齐，
# 因此表格总宽（半角单位）可精确预估。超过阈值换卡片布局，避免 phantom 裁切。
_GRID_COL_GUTTER = 2
_GRID_MAX_UNITS = 72
_GRID_BORDER = "1px solid color(var(--foreground) alpha(0.35))"
_GRID_ZEBRA = "color(var(--background) alpha(0.25))"


def _display_width(text: str) -> int:
    """字符串显示宽度：CJK/全角记 2，其余记 1（半角单位）。"""

    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _cell_text(cell_html: str) -> str:
    """单元格 HTML → 字面文本（剥离标签、还原实体）。"""

    return unescape(_INNER_TAG_RE.sub("", cell_html)).strip()


def _cell_units(cell_html: str) -> int:
    """单元格内容的显示宽度（内联标签本身不占宽）。"""

    return _display_width(_cell_text(cell_html))


def _plain_text(cell_html: str) -> str:
    return escape(_cell_text(cell_html), quote=False)


def _parse_table(inner: str):
    """表格内层 HTML → (header_cells|None, rows)。rows 为 ragged（各行列数可不同）。"""

    header = None
    body = inner
    m = _THEAD_RE.search(inner)
    if m:
        header = [c for _t, c in _CELL_RE.findall(m.group(1))]
        body = inner[:m.start()] + inner[m.end():]
    rows = [[c for _t, c in _CELL_RE.findall(rm.group(1))] for rm in _ROW_RE.finditer(body)]
    return header, rows


def convert_tables(html: str) -> str:
    """<table> → 窄表"等宽字体网格"，宽表"卡片"（minihtml 不支持 <table>）。

    - 网格：每列宽 = 该列内容最大显示宽度，nbsp 补齐 + 等宽字体保证跨行对齐；
      总宽可精确预估，超过 _GRID_MAX_UNITS 会被 phantom 裁切，故换卡片。
    - 卡片：每行一张卡，首列作标题，其余单元格以"表头名: 内容"逐行展示，
      正常 white-space 换行，任意宽度都不会裁切。
    """

    def repl(m):
        header, rows = _parse_table(m.group(1))
        if not header and not rows:
            return m.group(0)
        grid = _render_grid(header, rows)
        return grid if grid is not None else _render_cards(header, rows)

    return _TABLE_RE.sub(repl, html)


def _render_grid(header, rows):
    all_rows = ([header] if header else []) + rows
    ncols = max(len(r) for r in all_rows)
    if ncols == 0:
        return None
    if any(_RICH_CELL_RE.search(cell) for row in all_rows for cell in row):
        return None
    # 每格只测一次宽度，emit 阶段复用（strip/unescape/逐字符 east_asian_width 不便宜）
    units = [[_cell_units(c) for c in row] for row in all_rows]
    widths = [0] * ncols
    for row_units in units:
        for i, u in enumerate(row_units):
            widths[i] = max(widths[i], u)
    if sum(widths) + _GRID_COL_GUTTER * ncols > _GRID_MAX_UNITS:
        return None

    def row_html(row, row_units):
        # nbsp 补齐到列宽 + 列间 gutter；等宽字体下所有列的起始位置跨行对齐
        return "".join(
            cell.strip() + "&nbsp;" * (widths[i] - u + _GRID_COL_GUTTER)
            for i, (cell, u) in enumerate(zip(row, row_units))
        )

    lines = [
        '<div class="mip-tgrid" style="display:inline-block;border:%s;border-radius:4px;'
        'margin:6px 0;font-size:0.9rem;line-height:1.5;'
        # minihtml 预定义变量只有配色（无 --monospace），var() 回退语法无文档保证，
        # 对齐依赖等宽字体，必须写字面字体栈
        'font-family:Menlo, Consolas, DejaVu Sans Mono, monospace;">'
        % _GRID_BORDER
    ]
    if header:
        lines.append(
            '<div style="padding:2px 8px;white-space:nowrap;font-weight:bold;'
            'background-color:%s;border-bottom:%s;">%s</div>'
            % (_GRID_ZEBRA, _GRID_BORDER, row_html(header, units[0]))
        )
    for n, (row, row_units) in enumerate(zip(rows, units[1 if header else 0:])):
        zebra = "background-color:%s;" % _GRID_ZEBRA if n % 2 == 1 else ""
        lines.append(
            '<div style="padding:2px 8px;white-space:nowrap;%s">%s</div>'
            % (zebra, row_html(row, row_units))
        )
    lines.append("</div>")
    return "".join(lines)


def _render_cards(header, rows):
    lines = ['<div class="mip-tcards" style="border:%s;border-radius:4px;margin:6px 0;">' % _GRID_BORDER]
    labels = [_plain_text(h) for h in header] if header else None
    last = len(rows) - 1
    for n, row in enumerate(rows):
        sep = "border-bottom:%s;" % _GRID_BORDER if n < last else ""
        lines.append('<div style="padding:4px 8px 6px;%s">' % sep)
        for i, cell in enumerate(row):
            label = labels[i] if labels and i < len(labels) else ""
            if i == 0:
                # 首列作卡片标题
                lines.append('<div style="font-weight:bold;">%s</div>' % cell.strip())
            elif label:
                lines.append(
                    '<div style="margin-top:2px;color:var(--foreground);">'
                    '<span style="color:color(var(--foreground) alpha(0.7));">%s:</span> %s</div>'
                    % (label, cell.strip())
                )
            else:
                lines.append('<div style="margin-top:2px;">%s</div>' % cell.strip())
        lines.append("</div>")
    lines.append("</div>")
    return "".join(lines)


def convert_inputs(html: str) -> str:
    """<input type="checkbox"> → [x] / [ ]。"""

    def repl(m):
        return "[x]" if "checked" in m.group(0).lower() else "[ ]"

    return _INPUT_RE.sub(repl, html)


def convert_strikethrough(html: str) -> str:
    """<del>/<s> → <span style="text-decoration:line-through">（minihtml 不支持 del）。"""

    return _DEL_RE.sub(r'<span style="text-decoration:line-through;">\2</span>', html)


# ---------------------------------------------------------------------------
# 图片 base64 内嵌
# ---------------------------------------------------------------------------

# 扩展名 → data URL 子类型；svg 必须写成 svg+xml，否则 MIME 非法不渲染
_IMAGE_SUBTYPE = {
    "png": "png", "jpg": "jpeg", "jpeg": "jpeg", "gif": "gif",
    "webp": "webp", "bmp": "bmp", "ico": "x-icon", "svg": "svg+xml",
}

_IMG_SRC_RE = re.compile(r"<img[^>]*src=(\"|')(.*?)\1[^>]*>", re.S | re.I)

# (path, mtime_ns, size) → data URL。渲染在防抖 timer 里逐块重跑，
# 不缓存会在每次按键后重新读盘 + base64 编码（UI 线程上的最大开销）。
# 键含 mtime：同路径文件变更后只会新增条目，旧代必须回收；base64 是大字符串，
# 只限条数不限字节会把几十 MB 挂满整个会话生命周期，所以按总字节设预算。
_image_cache = {}
_image_cache_bytes = 0
_IMAGE_CACHE_MAX_BYTES = 32 * 1024 * 1024


def _image_cache_put(key, url):
    global _image_cache_bytes
    for k in [k for k in _image_cache if k[0] == key[0] and k != key]:
        _image_cache_bytes -= len(_image_cache.pop(k))
    _image_cache[key] = url
    _image_cache_bytes += len(url)
    while _image_cache and _image_cache_bytes > _IMAGE_CACHE_MAX_BYTES:
        _image_cache_bytes -= len(_image_cache.pop(next(iter(_image_cache))))


def _image_data_url(path):
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    url = _image_cache.get(key)
    if url is None:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        url = "data:image/%s;base64,%s" % (_IMAGE_SUBTYPE.get(ext, "png"), data)
        _image_cache_put(key, url)
    return url


def inline_local_images(html: str, base_dir: str = None) -> str:
    """本地图片 → data URL 内嵌；远程(http/https/data)原样保留。"""

    def repl(m):
        full = m.group(0)
        quote = m.group(1)
        src = m.group(2)
        low = src.lower()
        if low.startswith(("http://", "https://", "data:")):
            return full
        path = src if (os.path.isabs(src) or base_dir is None) else os.path.join(base_dir, src)
        if os.path.exists(path):
            try:
                data_url = _image_data_url(path)
            except OSError as exc:
                logger.warning("图片读取失败，保留原 src: %s (%s)", path, exc)
                return full
            return full.replace("%s%s%s" % (quote, src, quote), "%s%s%s" % (quote, data_url, quote), 1)
        return full

    return _IMG_SRC_RE.sub(repl, html)


# ---------------------------------------------------------------------------
# 样式
# ---------------------------------------------------------------------------

DEFAULT_STYLE = """
<style>
  body { font-family: var(--font); font-size: 1rem; line-height: 1.6; color: var(--foreground); }
  h1, h2, h3, h4, h5, h6 { color: var(--foreground); margin: 0.6em 0 0.3em; }
  code { background-color: color(var(--background) alpha(0.5)); padding: 1px 4px; border-radius: 3px; }
  pre { background-color: color(var(--background) alpha(0.5)); padding: 8px; border-radius: 4px; overflow: auto; }
  a { color: var(--accent); }
  blockquote { border-left: 3px solid var(--foreground); margin: 0; padding-left: 10px; opacity: 0.8; }
  hr { border: none; border-top: 1px solid var(--foreground); opacity: 0.3; }
  .c1 { color: var(--greenish); }
  .k  { color: var(--bluish); }
  .s, .s1, .s2 { color: var(--orangish); }
  .nf { color: var(--pinkish); }
  .nb { color: var(--cyanish); }
</style>
"""


# DEFAULT_STYLE 由 preview.py 在插入每个 phantom 时前置（每块是独立 minihtml 文档）。


# ---------------------------------------------------------------------------
# 按块分片（供 preview.py 逐块插 phantom）
# ---------------------------------------------------------------------------

_BLOCK_TAGS = {
    "div", "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "pre", "blockquote", "table", "hr", "img",
}


class _BlockSplitter(HTMLParser):
    # HTMLParser(convert_charrefs=True) 会把实体解码成字面文本，重序列化时必须
    # 重新 escape，否则代码块里的 &lt;b&gt; 会被还原成真标签（显示错误 + 注入标记）。
    # void 标签（<hr>/<img> 等非自闭合写法）没有闭合事件，不能压入 depth 栈。
    _VOID_TAGS = {"hr", "img", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self._current = []
        self._depth = 0

    def _starttag(self, tag, attrs, self_closing=False):
        s = "<" + tag
        for k, v in attrs:
            s += " %s" % k + (('="%s"' % escape(v, quote=True)) if v is not None else "")
        return s + "/>" if self_closing else s + ">"

    def _flush_current(self):
        if self._current:
            self.blocks.append("".join(self._current))
            self._current = []

    def _emit_void(self, tag, attrs):
        if self._depth == 0:
            self._flush_current()
            self.blocks.append(self._starttag(tag, attrs, self_closing=True))
        else:
            self._current.append(self._starttag(tag, attrs, self_closing=True))

    def handle_starttag(self, tag, attrs):
        if tag in self._VOID_TAGS:
            self._emit_void(tag, attrs)
            return
        if self._depth == 0 and tag in _BLOCK_TAGS:
            self._flush_current()
            self._depth = 1
            self._current.append(self._starttag(tag, attrs))
        elif self._depth > 0:
            self._depth += 1
            self._current.append(self._starttag(tag, attrs))

    def handle_startendtag(self, tag, attrs):
        if self._depth == 0 and tag in _BLOCK_TAGS:
            self._flush_current()
            self.blocks.append(self._starttag(tag, attrs, self_closing=True))
        else:
            self._current.append(self._starttag(tag, attrs, self_closing=True))

    def handle_endtag(self, tag):
        if tag in self._VOID_TAGS:
            return
        if self._depth > 0:
            self._current.append("</%s>" % tag)
            self._depth -= 1
            if self._depth == 0:
                self._flush_current()

    def handle_data(self, data):
        self._current.append(escape(data, quote=False))


def split_blocks(html: str) -> list:
    """把 HTML 按顶层块元素切成若干块，供 preview.py 逐块插入 phantom。"""
    p = _BlockSplitter()
    p.feed(html)
    p.close()
    if p._current:
        p.blocks.append("".join(p._current))
    return [b for b in p.blocks if b.strip()]


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------


# 闭合 --- 允许在文件末尾无换行处结束（(?:\n|\Z)），否则整段 front matter 漏进正文
_FRONT_MATTER_RE = re.compile(r"^\s*---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)


def front_matter_to_table(text: str):
    """抽取文档开头的 YAML front matter，转成规范 <table>（交给 convert_tables 显示）。

    返回 (剩余正文, table_html|None)。引擎无关——两个引擎对 front matter 处理不同，
    这里统一在渲染前抽出并预置一张表，避免依赖具体引擎行为。
    """
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return text, None
    rows = []
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            rows.append((k.strip(), v.strip()))
    if not rows:
        return text, None
    body = "".join(
        "<tr><td>%s</td><td>%s</td></tr>" % (escape(k, quote=False), escape(v, quote=False))
        for k, v in rows
    )
    table = (
        '<table class="mip-frontmatter">'
        "<thead><tr><th>key</th><th>value</th></tr></thead>%s</table>" % body
    )
    return text[m.end():], table


def render_raw(text: str, settings: dict, engine) -> str:
    """Markdown → 规范 HTML（引擎渲染 + front matter 抽表），两种预览共用的前半段管线。"""

    text, fm_table = front_matter_to_table(text)
    raw = engine.render(text, settings)
    return fm_table + raw if fm_table else raw


def render_html(text: str, settings: dict, engine, base_dir: str = None) -> str:
    """Markdown 文本 → 可在 phantom 中显示的 minihtml 字符串（整篇，未分片、未含样式）。

    样式由调用方（preview.py）逐块前置 DEFAULT_STYLE。
    """
    norm = normalize_html(render_raw(text, settings, engine))
    norm = convert_tables(norm)
    norm = convert_inputs(norm)
    norm = convert_strikethrough(norm)
    return inline_local_images(norm, base_dir=base_dir)


def render_body(text: str, settings: dict, engine, base_dir: str = None) -> str:
    """Markdown 文本 → 浏览器用正文 HTML 片段（browser 预览管线的前半段）。

    与 render_html 的关键区别：不做任何标签转换（浏览器原生支持 <table>/<input>/
    <del>），只做 front matter 抽取和本地图片 base64 内嵌（远程图片交给浏览器加载）。
    """

    return inline_local_images(render_raw(text, settings, engine), base_dir=base_dir)
