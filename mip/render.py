"""render.py — 规范 HTML → minihtml 适配。

minihtml 是 HTML 子集，明确不支持 <table>/<input>/<button>/<del> 等标签，
所以这里做三件事：
  1. 标签转换层：table→div 网格、input→[x]/[ ]、del/s→line-through（与引擎无关）
  2. 图片 base64 内嵌（仅本地图片同步内嵌；远程 http/https/data 原样保留）
  3. <style> 样式块（DEFAULT_STYLE）+ 按顶层块分片；样式由 preview.py 在
     插入每个 phantom 时前置（phantom 是独立 minihtml 文档，必须各自带样式）

全部是纯函数，可在无 Sublime 环境单测。
"""

import base64
import logging
import os
import re
from html import escape
from html.parser import HTMLParser

from .normalize import normalize_html

logger = logging.getLogger("MarkdownInlinePreview")


# ---------------------------------------------------------------------------
# 标签转换层
# ---------------------------------------------------------------------------

_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.S | re.I)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t([hd])[^>]*>(.*?)</t\1>", re.S | re.I)
_INPUT_RE = re.compile(r"<input[^>]*type=[\"']?checkbox[\"']?[^>]*>", re.S | re.I)
_DEL_RE = re.compile(r"<(del|s)(?=[\s>/])[^>]*>(.*?)</\1>", re.S | re.I)


def convert_tables(html: str) -> str:
    """<table> → 嵌套 <div> 网格（display:inline-block + border）。

    minihtml 不支持 <table>，这是 GFM 表格能显示的唯一途径。
    """

    def repl(m):
        rows = _ROW_RE.findall(m.group(1))
        out_rows = []
        for row in rows:
            cells = _CELL_RE.findall(row)
            cell_divs = "".join(
                '<div style="display:inline-block;border:1px solid var(--foreground);'
                'padding:2px 6px;vertical-align:top;margin:-0.5px;">%s</div>' % c
                for _tag, c in cells
            )
            out_rows.append('<div style="white-space:nowrap;">%s</div>' % cell_divs)
        return '<div style="margin:4px 0;">%s</div>' % "".join(out_rows)

    return _TABLE_RE.sub(repl, html)


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
_image_cache = {}
_IMAGE_CACHE_MAX = 64


def _image_data_url(path):
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    url = _image_cache.get(key)
    if url is None:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        url = "data:image/%s;base64,%s" % (_IMAGE_SUBTYPE.get(ext, "png"), data)
        if len(_image_cache) >= _IMAGE_CACHE_MAX:
            _image_cache.clear()
        _image_cache[key] = url
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


def render_html(text: str, settings: dict, engine, base_dir: str = None) -> str:
    """Markdown 文本 → 可在 phantom 中显示的 minihtml 字符串（整篇，未分片、未含样式）。

    样式由调用方（preview.py）逐块前置 DEFAULT_STYLE。
    """
    text, fm_table = front_matter_to_table(text)
    raw = engine.render(text, settings)
    if fm_table:
        raw = fm_table + raw
    norm = normalize_html(raw)
    norm = convert_tables(norm)
    norm = convert_inputs(norm)
    norm = convert_strikethrough(norm)
    norm = inline_local_images(norm, base_dir=base_dir)
    return norm
