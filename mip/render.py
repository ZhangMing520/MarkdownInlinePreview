"""render.py — Markdown 渲染管线的共享前半段 + minihtml 适配后半段。

编排（见文件底部）：render_raw（引擎 + front matter）两种预览共用；
render_html 在其后加 minihtml 适配，render_body 直接内嵌图片给浏览器用。

minihtml 是 HTML 子集，明确不支持 <table>/<input>/<button>/<del> 等标签，
且没有 width/百分比/flexbox/overflow 滚动（官方 minihtml 文档已核实），
所以适配层做三件事：
  1. 标签转换层：table→等宽字体网格或卡片、input→[x]/[ ]、
     del/s→U+0336 组合删除线、pre→pre-wrap(4170+)或逐行 div(旧构建)（与引擎无关）
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
_PRE_RE = re.compile(r"(<pre[^>]*>)(.*?)(</pre>)", re.S | re.I)
# 标签之间的纯空白文本（pygments 把缩进/对齐空白编码为 <span class="w">  </span>）
_PRE_WS_BETWEEN_TAGS_RE = re.compile(r"(>)([ \t]+)(?=<)")
_PRE_LEADING_WS_RE = re.compile(r"^[ \t]+")
# <pre> 内的 <code> 包裹（codehilite 还在其前面放一个空 <span></span> 行号占位）：
# legacy 逐行拆 <div> 前整体剥离，否则 <code>/</code> 会跨首末行劈裂、中间行丢 code 上下文
_PRE_CODE_WRAP_RE = re.compile(r"^(?:<span></span>)?<code[^>]*>|</code>$", re.I)
# CSS white-space 模型：<pre> 首尾紧贴的单个换行被抑制，不产生空行 div
_PRE_BOUNDARY_NL_RE = re.compile(r"^\n|\n$")
# U+0336 COMBINING LONG STROKE OVERLAY：minihtml 官方仅支持 text-decoration
# none/underline，line-through 被静默丢弃，删除线只能逐字叠加组合字符实现
_STRIKE_MARK = "\u0336"
# del/s 内层切词：标签 | 数字/十六进制/命名实体 | 连续空白 | 其余单字符
# 兜底用 [^\s]（含 <）而非 [^\s<]：不构成合法标签的孤立 < 若被排除，findall 会整字符
# 丢弃（删除线文本少一个字）；保留后 tok[0]=="<" 分支不给它叠标记，仅原样透传。
_STRIKE_TOKEN_RE = re.compile(
    r"<[^>]+>|&#\d+;|&#x[0-9a-fA-F]+;|&[a-zA-Z][a-zA-Z0-9]+;|\s+|[^\s]"
)
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


def _strike_text(inner: str) -> str:
    """del/s 内层 HTML → 每个可见字符后叠 U+0336（实体作为一个整体，
    组合符作用于实体解析后的字符；标签与连续空白原样保留）。"""

    out = []
    for tok in _STRIKE_TOKEN_RE.findall(inner):
        out.append(tok)
        if tok[0] != "<" and not tok[0].isspace():
            out.append(_STRIKE_MARK)
    return "".join(out)


def convert_strikethrough(html: str) -> str:
    """<del>/<s> → U+0336 逐字删除线。

    minihtml 官方 text-decoration 仅支持 none/underline，line-through 会被
    静默丢弃（旧实现输出的 span 在真机上无任何删除线效果）；改用组合字符
    U+0336（COMBINING LONG STROKE OVERLAY）逐字叠加，由字体 shaping 划线。
    del/s 内层若含行内标签（code/strong 等）或 HTML 实体也能正确处理。
    """

    return _DEL_RE.sub(lambda m: _strike_text(m.group(2)), html)


def _legacy_pre_line(line: str) -> str:
    """旧构建降级：一行代码 HTML 中的缩进/对齐空白转 &nbsp;（normal 空白会被折叠）。"""

    # pygments：空白整段在 <span class="w">  </span> 里（标签之间的纯空白文本节点）
    line = _PRE_WS_BETWEEN_TAGS_RE.sub(
        lambda m: m.group(1) + "&nbsp;" * len(m.group(2).expandtabs(4)), line
    )
    # markdown-it-py：围栏块无高亮，缩进是行首裸文本
    m = _PRE_LEADING_WS_RE.match(line)
    if m:
        line = "&nbsp;" * len(m.group(0).expandtabs(4)) + line[m.end():]
    return line


def convert_code_blocks(html: str, pre_wrap: bool = True) -> str:
    """<pre> 代码块适配 minihtml（minihtml 受支持标签白名单不含 <pre>）。

    未知标签 <pre> 按普通块渲染且 white-space 固定 normal：换行折叠、缩进塌缩
    （真机截图确认整段代码连成一片）。Build 4170+ 支持 white-space: pre-wrap，
    保留原生 <pre> 由 CSS 接管；旧构建（插件最低支持 4000）降级为每行一个官方
    支持的 <div>（块级天然换行），空白转 &nbsp;，空行放 nbsp 占位保住行高。
    长行在旧构建上不能按词换行（无 overflow/横向滚动），是可接受的降级。
    """

    if pre_wrap:
        return html

    def repl(m):
        # 整体剥离 <code> 包裹（见 _PRE_CODE_WRAP_RE），再按 CSS white-space 模型抑制
        # 首尾紧贴换行——剥 <code> 后残留的 <code>\n 也算首换行。.mip-pre 的 CSS 已接管
        # 代码块外观，去掉 <code> 也免与内联 code 规则叠出双重背景。
        inner = _PRE_CODE_WRAP_RE.sub("", m.group(2))
        inner = _PRE_BOUNDARY_NL_RE.sub("", inner)
        parts = ['<div class="mip-pre">']
        for line in inner.split("\n"):
            content = _legacy_pre_line(line)
            # 空行：nbsp 占位保住行高
            if not _INNER_TAG_RE.sub("", content).strip():
                content += "&nbsp;"
            parts.append("<div>%s</div>" % content)
        parts.append("</div>")
        return "".join(parts)

    return _PRE_RE.sub(repl, html)


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
  /* 排版向浏览器模式的 GitHub CSS 看齐（browser_server.py 的 GITHUB_CSS，数值一一对应），
     但不能直接复用同一份：minihtml 是白名单引擎，不认 @media/:root/:nth-child/相邻/属性
     选择器与 width/flex/overflow/600 字重；且表格/复选框/删除线已在 render.py 转成
     minihtml 结构。这里只翻译受支持的字号/字重/行高/边框。
     间距维度与浏览器不同：每个块挂在独立空占位行上（见 preview.py 的 "\n" 占位缓冲），
     占位行自带约一行高（≈25px，已大于 GitHub 标题 24px/块 16px 的 margin）；minihtml 的
     margin 又只接受正值、无法抵消占位行，故块 margin 一律 0，间距统一由占位行提供。 */
  h1, h2, h3, h4, h5, h6 { color: var(--foreground); margin: 0; font-weight: bold; line-height: 1.25; }
  h1 { font-size: 2em; }
  h2 { font-size: 1.5em; }
  h3 { font-size: 1.25em; }
  h4 { font-size: 1em; }
  h5 { font-size: 0.875em; }
  h6 { font-size: 0.85em; }
  /* 对应 GITHUB_CSS 的 h1/h2 border-bottom（border-soft 很淡）：用前景色低透明跟随配色 */
  h1, h2 { border-bottom: 1px solid color(var(--foreground) alpha(0.18)); padding-bottom: 0.3em; }
  code { background-color: color(var(--background) alpha(0.5)); padding: 1px 4px; border-radius: 3px; }
  /* <pre> 不在 minihtml 受支持标签白名单内（官方文档），未知标签默认 white-space:normal，
     必须显式 pre-wrap 否则换行折叠、缩进塌缩；pre-wrap 需 Build 4170+，
     旧构建由 convert_code_blocks 转成 .mip-pre（每行一 div）。overflow 不被支持，不写。 */
  pre { background-color: color(var(--background) alpha(0.5)); padding: 8px; border-radius: 4px;
        white-space: pre-wrap; font-family: Menlo, Consolas, DejaVu Sans Mono, monospace; }
  .mip-pre { background-color: color(var(--background) alpha(0.5)); padding: 8px; border-radius: 4px;
             font-family: Menlo, Consolas, DejaVu Sans Mono, monospace; }
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


def render_html(text: str, settings: dict, engine, base_dir: str = None,
                pre_wrap: bool = True) -> str:
    """Markdown 文本 → 可在 phantom 中显示的 minihtml 字符串（整篇，未分片、未含样式）。

    pre_wrap：宿主 Build 4170+ 时为 True，<pre> 保留原样由 CSS pre-wrap 接管；
    旧构建传 False 走 div 降级（见 convert_code_blocks）。
    样式由调用方（preview.py）逐块前置 DEFAULT_STYLE。
    """
    norm = normalize_html(render_raw(text, settings, engine))
    norm = convert_code_blocks(norm, pre_wrap)
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
