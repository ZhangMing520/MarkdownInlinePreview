"""browser_server.py — 浏览器实时预览的纯 Python 部分：HTTP 服务器 + SSE 推送 + 完整 HTML 模板。

不 import sublime，可在 .venv 直测。设计要点：

- 只绑定 127.0.0.1，路径按 doc_id 隔离，多窗口共用一个服务器实例；
  Host 头只接受 127.0.0.1/localhost（防 DNS rebinding）
- SSE 只推正文快照（JSON 单行编码），整页骨架在 GET /<doc> 时组装；
  EventSource 断线自动重连，无需心跳
- 客户端注册时立刻入队当前快照，消除"先 GET 页面后连 SSE"间隙内丢掉的更新
- 页面模板/样式全部内嵌，浏览器端零外部请求，离线可用
"""

import json
import logging
import os
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from string import Template

from . import vendor_loader

logger = logging.getLogger("MarkdownInlinePreview")

# ---------------------------------------------------------------------------
# 样式与页面模板（浏览器端零外部依赖：CSS 全内嵌，不引用任何 CDN）
# ---------------------------------------------------------------------------

# GitHub 风格样式表——每个值都有出处，两类来源：
#   [实测] github.com 文件页（blob）article.markdown-body 的 computed style，
#          2026-10-04 于 1440px 视口量得（列宽 1006px、行高 24px、段距 16px、h2 margin 24/16 等）
#   [gmc]  github-markdown-css 5.8.1（GitHub 官方 markdown 样式的社区权威提取版，npmmirror 可查证）
#   [增补] GitHub 未定义、为本地体验有意添加的规则（每处注明理由）
# 亮暗色板均为 Primer 当前 token；跟随系统 prefers-color-scheme（与 github.com 行为一致）。
# 代码高亮色由 pygments 的 get_style_defs 生成后经 $code_css 注入。
GITHUB_CSS = """\
:root {
  /* [gmc light] fg #1f2328 / canvas #ffffff / border #d1d9e0 / canvas-subtle #f6f8fa
     muted #59636e / accent #0969da；内联代码底 #818b981f（中性色 12% 透明）；
     border-soft = 官方的 #d1d9e0b3（70% 透明，用于 h1-h2 下划线与表格行线） */
  --bg: #ffffff; --fg: #1f2328; --muted: #59636e; --border: #d1d9e0;
  --border-soft: #d1d9e0b3; --code-bg: #f6f8fa; --code-inline-bg: #818b981f;
  --link: #0969da;
}
@media (prefers-color-scheme: dark) {
  :root {
    /* [gmc dark] canvas #0d1117 / fg #f0f6fc / border #3d444d / muted #9198a1
       canvas-subtle #151b23 / accent #4493f8 */
    --bg: #0d1117; --fg: #f0f6fc; --muted: #9198a1; --border: #3d444d;
    --border-soft: #3d444db3; --code-bg: #151b23; --code-inline-bg: #6e768166;
    --link: #4493f8;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  /* [gmc] 官方正文栈；[增补] 显式插入 CJK 三平台字体（PingFang/雅黑）：GitHub 靠系统回退，
     不写时 Linux/Windows 中文回退字体不可控（无中文 monospace 时会缺字形） */
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial,
    "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif,
    "Apple Color Emoji", "Segoe UI Emoji";
  /* [实测] 16px / 1.5（行高实测 24px） */
  font-size: 16px; line-height: 1.5;
}
/* [实测] GitHub blob 页正文列宽 1006px（经典布局常量 1012px）；居中与 GitHub 页面布局一致，
   实际原因是可读性：一行超过约 100 字符后回读易串行 */
#content { max-width: 1012px; margin: 0 auto; padding: 32px; }
/* [gmc] h1-h6: margin 1.5rem/1rem、行高 1.25、weight 600；h1 2em、h2 1.5em、h3 1.25em；
   h1/h2 下划线 padding .3em + 1px border-soft（实测 7.2px = .3em × 24px 吻合） */
h1, h2, h3, h4, h5, h6 { margin: 24px 0 16px; line-height: 1.25; font-weight: 600; }
h1 { font-size: 2em; }
h2 { font-size: 1.5em; }
h3 { font-size: 1.25em; }
h1, h2 { border-bottom: 1px solid var(--border-soft); padding-bottom: .3em; }
/* [gmc] 统一块间距：段落/引用/列表/表格/代码块下边距 1rem（实测 16px），一处声明 */
p, blockquote, ul, ol, table { margin: 0 0 16px; }
/* [gmc] 链接默认带下划线 */
a { color: var(--link); text-decoration: underline; }
img { max-width: 100%; }
/* [gmc] hr: 高 .25em、bg border 色、margin 1.5rem */
hr { border: none; height: .25em; background: var(--border); margin: 24px 0; }
code, pre, kbd {
  /* [gmc] 官方等宽栈（原样，勿加自选字体） */
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
    "Liberation Mono", monospace;
  font-size: 85%;
}
/* [gmc] 内联代码：padding .2em .4em、85%、底 #818b981f、radius 6px */
code { background: var(--code-inline-bg); border-radius: 6px; padding: .2em .4em; }
/* [gmc] 代码块容器：canvas-subtle 底、radius 6px、padding 1rem、可横向滚动、行高 1.45 */
pre, .codehilite {
  background: var(--code-bg); border-radius: 6px; padding: 16px;
  overflow: auto; line-height: 1.45;
}
pre code { background: none; padding: 0; font-size: 100%; }
.codehilite pre { background: none; padding: 0; margin: 0; }
/* [gmc] 引用：padding 0 1em、muted 色、左线 .25em border 色 */
blockquote {
  padding: 0 1em; color: var(--muted);
  border-left: .25em solid var(--border);
}
/* [gmc] 表格：th/td padding 6px 13px、1px border；行上边线 border-soft；
   偶数行斑马纹 canvas-subtle（margin 归上方统一块间距规则） */
table { border-collapse: collapse; display: block; overflow: auto; }
th, td { border: 1px solid var(--border); padding: 6px 13px; }
th { font-weight: 600; }
tr { border-top: 1px solid var(--border-soft); }
tr:nth-child(2n) { background: var(--code-bg); }
/* [gmc] 列表 padding-left 2em；li 间距 .25em（实测约合 4px） */
ul, ol { padding-left: 2em; }
li + li { margin-top: .25em; }
/* [增补] 任务列表复选框与文字的间距（GitHub 由 .task-list-item-controls 精细排版，这里取等效间距） */
li input[type="checkbox"] { margin-right: 6px; }
/* [增补] 删除线弱化处理：GitHub 渲染 del 为普通删除线；muted 提高视觉区分度（可辨识但不抢眼） */
del, s { color: var(--muted); }
"""

# $code_css 为 pygments 样式；$extras_head 为 KaTeX/mermaid 的 <link>/<script>（不启用时为空）。
# SSE 收到 {"h": html} 换正文、{"s": ratio} 按比例滚动；enhance() 由 extras 注入（公式/图渲染）。
PAGE_TEMPLATE = Template("""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>$github_css</style>
<style>$code_css</style>
$extras_head
</head>
<body>
<article id="content">$body</article>
<script>
$extras_js
(function () {
  var el = document.getElementById("content");
  function refresh() {
    if (typeof enhance === "function") { try { enhance(); } catch (e) {} }
  }
  // EventSource 必须用绝对路径：页面 URL /{doc} 无尾斜杠，相对 "events" 会解析成根级 /events 而 404。
  // 注意正则结尾的双美元号是 string.Template 的转义（单个会被当占位符报错）
  var es = new EventSource(location.pathname.replace(/\\/+$$/, "") + "/events");
  es.onmessage = function (ev) {
    var msg = JSON.parse(ev.data);
    if (msg.h !== undefined) { el.innerHTML = msg.h; refresh(); }
    if (msg.s !== undefined) {
      window.scrollTo(0, (document.documentElement.scrollHeight - window.innerHeight) * msg.s);
    }
  };
  if (document.readyState === "complete") { refresh(); }
  else { window.addEventListener("load", refresh); }
})();
</script>
</body>
</html>
""")

# KaTeX/mermaid 客户端增强脚本（普通字符串而非 Template：内容含 $$ 定界符，过 Template 会转义丢字）
_EXTRAS_JS = """
function enhance() {
  var el = document.getElementById("content");
  el.querySelectorAll("code.language-mermaid").forEach(function (code) {
    var pre = document.createElement("pre");
    pre.className = "mermaid";
    pre.textContent = code.textContent;
    code.parentNode.replaceWith(pre);
  });
  if (window.renderMathInElement) {
    renderMathInElement(el, {
      delimiters: [
        {left: "$$", right: "$$", display: true},
        {left: "\\\\[", right: "\\\\]", display: true},
        {left: "\\\\(", right: "\\\\)", display: false},
        {left: "$", right: "$", display: false}
      ],
      throwOnError: false
    });
  }
  if (window.mermaid) {
    try { mermaid.run({nodes: el.querySelectorAll("pre.mermaid")}); } catch (e) {}
  }
}
window.addEventListener("load", function () {
  if (window.mermaid) {
    var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    mermaid.initialize({startOnLoad: false, theme: dark ? "dark" : "default"});
  }
});
"""

_EXTRAS_HEAD = (
    '<link rel="stylesheet" href="static/katex/katex.min.css">\n'
    '<script src="static/katex/katex.min.js"></script>\n'
    '<script src="static/katex/auto-render.min.js"></script>\n'
    '<script src="static/mermaid/mermaid.min.js"></script>'
)


def build_page(title: str, body_html: str, code_css: str = "", extras: bool = False) -> str:
    """组装完整 HTML 文档（初始渲染 + SSE 客户端脚本 + 可选公式/图增强）。"""

    return PAGE_TEMPLATE.substitute(
        title=escape(title, quote=False),
        github_css=GITHUB_CSS,
        code_css=code_css,
        body=body_html,
        extras_head=_EXTRAS_HEAD if extras else "",
        extras_js=_EXTRAS_JS if extras else "",
    )


_PYMENTS_CSS = None


def pygments_css() -> str:
    """codehilite 高亮样式表（pygments 缺失则为空串）。

    样式只取决于固定 style 名，每次渲染重算纯属浪费，模块级缓存一次。
    """

    global _PYMENTS_CSS
    if _PYMENTS_CSS is None:
        try:
            from pygments.formatters import HtmlFormatter

            _PYMENTS_CSS = HtmlFormatter(style="friendly").get_style_defs(".codehilite")
        except ImportError:
            _PYMENTS_CSS = ""
    return _PYMENTS_CSS


# ---------------------------------------------------------------------------
# 静态资源（KaTeX/mermaid，zip 安装时 vendor_loader 解压到缓存）
# ---------------------------------------------------------------------------

_STATIC_MIME = {
    ".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2",
    ".woff": "font/woff", ".svg": "image/svg+xml", ".json": "application/json",
}
_static_map = None
_static_lock = threading.Lock()


def _static_assets():
    """relpath → 绝对路径映射（懒构建一次；.ok 哨兵文件排除）。构建后无锁读取。"""

    global _static_map
    mapping = _static_map
    if mapping is None:
        with _static_lock:
            if _static_map is None:
                built = {}
                assets = vendor_loader.resolve_assets_dir()
                for root, _dirs, files in os.walk(assets):
                    for fn in files:
                        if fn == ".ok":
                            continue
                        full = os.path.join(root, fn)
                        built[os.path.relpath(full, assets).replace(os.sep, "/")] = full
                _static_map = built
            mapping = _static_map
    return mapping


def lookup_static(rel: str):
    """仅允许映射内已有条目，天然免疫路径穿越。"""

    return _static_assets().get(rel)


# ---------------------------------------------------------------------------
# HTTP 服务器 + SSE
# ---------------------------------------------------------------------------


def _sse_frame(key: str, value) -> bytes:
    """一条 SSE 消息（JSON 单行编码）。每次更新只编码一次，各连接共享同一份字节。"""

    return ("data: %s\n\n" % json.dumps({key: value})).encode("utf-8")


class _Client:
    """一个 SSE 连接的待发送帧：按键（"h"/"s"）各占一个槽位、后写覆盖先写。

    不用单一 maxsize=1 队列：那样高频的滚动推送会挤掉尚未发出的 HTML 快照，
    反之亦然；分槽后两类更新互不丢失。close() 唤醒阻塞中的连接（shutdown 用）。
    """

    __slots__ = ("pending", "cond", "closed")

    def __init__(self):
        self.pending = {}
        self.cond = threading.Condition()
        self.closed = False

    def offer(self, key, frame):
        with self.cond:
            if not self.closed:
                self.pending[key] = frame
                self.cond.notify()

    def pop_pending(self):
        """阻塞至有待发送帧（或连接被关闭）；返回 None 表示应退出事件循环。"""

        with self.cond:
            while not self.pending:
                if self.closed:
                    return None
                self.cond.wait()
            frames = list(self.pending.values())
            self.pending.clear()
            return frames

    def close(self):
        with self.cond:
            self.closed = True
            self.cond.notify_all()


class _Doc:
    __slots__ = ("body", "code_css", "extras", "clients", "lock")

    def __init__(self):
        self.body = ""
        self.code_css = ""
        self.extras = False
        self.clients = set()
        # body 赋值与 clients 快照共用此锁：新连接注册时补推的快照不会比
        # 并发 update 推的旧，二者不会乱序
        self.lock = threading.Lock()

    def snapshot_page(self):
        with self.lock:
            return build_page("Markdown Preview", self.body, self.code_css, extras=self.extras)

    def update(self, body_html, code_css, extras):
        """更新正文并广播（单临界区：赋值与推送原子发生）。"""

        frame = _sse_frame("h", body_html)
        with self.lock:
            self.body = body_html
            self.code_css = code_css
            self.extras = extras
            for c in self.clients:
                c.offer("h", frame)

    def scroll(self, ratio):
        frame = _sse_frame("s", ratio)
        with self.lock:
            for c in self.clients:
                c.offer("s", frame)

    def close_clients(self):
        with self.lock:
            clients = list(self.clients)
            self.clients.clear()
        for c in clients:
            c.close()


class _SSEHandler(BaseHTTPRequestHandler):
    # HTTP/1.0：页面响应带 Content-Length 后即断开，SSE 连接由循环维持；
    # EventSource 断线自动重连，无需 keep-alive/心跳
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        logger.debug("MarkdownInlinePreview browser: " + fmt, *args)

    @property
    def docs(self):
        return self.server.docs

    def _host_allowed(self):
        # DNS rebinding 防护：服务器只绑 127.0.0.1，但恶意域名解析到本机后
        # 浏览器仍会带上其 Host 发起请求，这里按绑定端口白名单拒绝非本机 Host
        host = (self.headers.get("Host") or "").strip().lower()
        if ":" in host:
            name, _, port = host.rpartition(":")
        else:
            name, port = host, ""
        if name not in ("127.0.0.1", "localhost"):
            return False
        return port in ("", str(self.server.server_address[1]))

    def do_GET(self):
        if not self._host_allowed():
            self.send_error(403)
            return
        path = self.path.strip("/")
        # 不用 str.removesuffix：ST 3.8 插件宿主没有这个 API
        if path == "favicon.ico":
            self.send_error(404)
        elif path.startswith("static/"):
            self._static(path[len("static/"):])
        elif path.endswith("/events"):
            self._sse(path[: -len("/events")])
        elif path in self.docs:
            self._page(path)
        else:
            self.send_error(404)

    def _static(self, rel):
        full = lookup_static(rel)
        if full is None:
            self.send_error(404)
            return
        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError:
            logger.debug("静态资源读取失败: %s", full)
            self.send_error(404)
            return
        self.send_response(200)
        ext = os.path.splitext(full)[1].lower()
        self.send_header("Content-Type", _STATIC_MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _page(self, doc_id):
        # 完整文档在请求时组装：SSE 只推正文，页面骨架（样式/脚本）只存一份
        body = self.docs[doc_id].snapshot_page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _sse(self, doc_id):
        doc = self.docs.get(doc_id)
        if doc is None:
            self.send_error(404)
            return
        client = _Client()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            # 注册即补推当前快照，补上 GET 页面与 SSE 建连之间可能发生的更新；
            # 与 body 赋值同锁，保证不会推入比并发更新更旧的快照
            with doc.lock:
                doc.clients.add(client)
                client.offer("h", _sse_frame("h", doc.body))
            while True:
                frames = client.pop_pending()
                if frames is None:
                    break
                self.wfile.write(b"".join(frames))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # 页面刷新/关闭的常规断连，debug 级即可（正常操作每次刷新都会产生一条）
            logger.debug("SSE 客户端断开: %s", doc_id)
        finally:
            with doc.lock:
                doc.clients.discard(client)

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()


class LiveServer:
    """多文档实时预览服务器。ensure_started 后可随时 set_page/push_scroll。"""

    def __init__(self):
        self.docs = {}
        self._httpd = None
        self._thread = None
        self._lock = threading.Lock()

    @property
    def base_url(self):
        if self._httpd is None:
            return None
        return "http://127.0.0.1:%d" % self._httpd.server_address[1]

    def ensure_started(self):
        with self._lock:
            if self._httpd is not None:
                return
            self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _SSEHandler)
            self._httpd.daemon_threads = True
            # handler 经 self.server.docs 取文档；dict 身份不变，setdefault 仍作用于 LiveServer
            self._httpd.docs = self.docs
            self._thread = threading.Thread(
                target=self._httpd.serve_forever,
                name="MarkdownInlinePreview-browser",
                daemon=True,
            )
            self._thread.start()
            logger.info("MarkdownInlinePreview: 浏览器预览服务器已启动 %s", self.base_url)

    def set_page(self, doc_id: str, body_html: str, code_css: str = None, extras: bool = False):
        """更新文档正文并推送给已连接的客户端（SSE 只传正文，不传整页）。

        code_css 缺省时用 pygments 样式（高亮是页面组装侧的事，调用方不必关心）。
        """

        with self._lock:
            doc = self.docs.setdefault(doc_id, _Doc())
        doc.update(body_html, pygments_css() if code_css is None else code_css, extras)

    def push_scroll(self, doc_id: str, ratio: float):
        doc = self.docs.get(doc_id)
        if doc is not None:
            doc.scroll(ratio)

    def remove_page(self, doc_id: str):
        with self._lock:
            doc = self.docs.pop(doc_id, None)
        if doc is not None:
            doc.close_clients()

    def shutdown(self):
        with self._lock:
            if self._httpd is None:
                return
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._thread = None
            docs = list(self.docs.values())
            self.docs.clear()
        # 唤醒阻塞在 pop_pending 上的 SSE 线程（daemon 线程也要立即退出，
        # 不留挂着 cond.wait 的引用）
        for doc in docs:
            doc.close_clients()
        logger.info("MarkdownInlinePreview: 浏览器预览服务器已停止")
