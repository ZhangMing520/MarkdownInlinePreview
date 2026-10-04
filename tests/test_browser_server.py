"""browser_server 服务器 + SSE 推送 + 页面组装的直测（无 Sublime）。"""

import http.client
import os
import json

import pytest

from mip.browser_server import LiveServer, build_page
from mip.render import render_body
from conftest import SETTINGS
from mip.engines.py_md import PythonMarkdownEngine


@pytest.fixture
def server():
    srv = LiveServer()
    srv.ensure_started()
    yield srv
    srv.shutdown()


def _connect(base_url, path, headers=None, timeout=5):
    # base_url 形如 http://127.0.0.1:PORT
    host, port = base_url[len("http://"):].rsplit(":", 1)
    conn = http.client.HTTPConnection(host, int(port), timeout=timeout)
    conn.request("GET", path, headers=headers or {})
    return conn, conn.getresponse()


def _get(base_url, path, **kw):
    conn, resp = _connect(base_url, path, **kw)
    return resp, conn


def test_page_served(server):
    # set_page 只存正文，完整文档在 GET 时由 build_page 组装
    server.set_page("d1", "<p>hello</p>")
    resp, conn = _get(server.base_url, "/d1")
    assert resp.status == 200
    body = resp.read().decode()
    conn.close()
    assert "<p>hello</p>" in body
    assert "EventSource" in body        # SSE 客户端脚本
    assert "prefers-color-scheme" in body  # 内嵌样式（亮暗两套）


def test_host_header_validated(server):
    # DNS rebinding 防护：伪造 Host 一律 403
    server.set_page("d1", "<p>secret</p>")
    conn, resp = _connect(server.base_url, "/d1", headers={"Host": "evil.example.com"})
    assert resp.status == 403
    conn.close()
    # 正确 Host 照常工作
    resp, conn = _get(server.base_url, "/d1")
    assert resp.status == 200
    conn.close()


def test_unknown_doc_404(server):
    resp, conn = _get(server.base_url, "/nope")
    assert resp.status == 404
    conn.close()


def _open_sse(server, doc_id):
    conn, resp = _connect(server.base_url, "/%s/events" % doc_id)
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "text/event-stream"

    def read_event():
        # SSE 事件以空行结尾；逐行读到 data: 行；EOF（服务器已关闭）返回 None
        while True:
            raw = resp.fp.readline()
            if not raw:
                return None
            line = raw.decode().strip()
            if line.startswith("data: "):
                return json.loads(line[len("data: "):])

    return conn, read_event


def test_sse_push(server):
    server.set_page("d1", "<p>v1</p>")
    conn, read_event = _open_sse(server, "d1")

    # 注册即收到当前快照（补建连间隙）；只含正文，不含整页骨架
    snap = read_event()
    assert "<p>v1</p>" in snap["h"]
    assert "<!DOCTYPE" not in snap["h"] and "<style" not in snap["h"]
    # 运行中推送新快照
    server.set_page("d1", "<p>v2</p>")
    assert "<p>v2</p>" in read_event()["h"]
    # 滚动与正文各占独立槽位：滚动不会挤掉待发的正文快照
    server.push_scroll("d1", 0.5)
    server.set_page("d1", "<p>v3</p>")
    got = {}
    for _ in range(2):
        got.update(read_event())
    assert got["s"] == 0.5 and "<p>v3</p>" in got["h"]
    conn.close()


def test_sse_404_for_unknown_doc(server):
    conn, resp = _connect(server.base_url, "/nope/events")
    assert resp.status == 404
    conn.close()


def test_shutdown_wakes_sse_threads(server):
    # 阻塞在 pop_pending 的 SSE 线程必须被 shutdown 的关闭信号唤醒并结束
    server.set_page("d1", "<p>x</p>")
    conn, read_event = _open_sse(server, "d1")
    assert read_event() is not None  # 初始快照
    server.shutdown()
    assert read_event() is None      # handler 退出 → 连接 EOF
    conn.close()


def test_push_no_clients_ok(server):
    server.set_page("d1", "<p>x</p>")  # 无客户端连接也不得报错
    server.push_scroll("d1", 0.1)
    server.remove_page("d1")
    resp, conn = _get(server.base_url, "/d1")
    assert resp.status == 404
    conn.close()


def test_page_events_url_is_absolute():
    # 回归：页面 URL 是 /{doc}（无尾斜杠），相对 "events" 会被解析成 /events 而 404，
    # SSE 通道整个失效（实时刷新/滚动全断）。2026-10-04 真浏览器复现。
    page = build_page("t", "<p>b</p>")
    assert 'new EventSource(location.pathname' in page


def test_build_page_structure():
    page = build_page("t", "<p>b</p>", ".codehilite .k { color: red; }")
    assert "<title>t</title>" in page
    assert "<p>b</p>" in page
    assert ".codehilite .k" in page


def test_render_body_keeps_native_tags():
    # 与 minihtml 管线不同：表格等原生标签原样保留，不做转换
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    page = build_page("Markdown Preview", render_body(md, SETTINGS, PythonMarkdownEngine()))
    assert "<table>" in page
    assert "mip-tgrid" not in page and "mip-tcards" not in page
    assert "EventSource" in page


def test_render_body_inlines_local_images(tmp_path):
    import base64
    png = tmp_path / "x.png"
    png.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"))
    md = "![a](x.png)\n"
    body = render_body(md, SETTINGS, PythonMarkdownEngine(), base_dir=str(tmp_path))
    assert "data:image/png;base64," in body


def test_multiple_docs_isolated(server):
    server.set_page("a", "<p>A</p>")
    server.set_page("b", "<p>B</p>")
    ra, ca = _get(server.base_url, "/a")
    rb, cb = _get(server.base_url, "/b")
    assert "<p>A</p>" in ra.read().decode()
    assert "<p>B</p>" in rb.read().decode()
    ca.close()
    cb.close()


def test_server_restart(server):
    server.shutdown()
    assert server.base_url is None
    server.ensure_started()
    server.set_page("d", "<p>after</p>")
    resp, conn = _get(server.base_url, "/d")
    assert "<p>after</p>" in resp.read().decode()
    conn.close()


def test_build_page_extras():
    plain = build_page("t", "<p>b</p>")
    assert "katex" not in plain and "mermaid" not in plain
    full = build_page("t", "<p>b</p>", extras=True)
    assert "static/katex/katex.min.js" in full
    assert "static/mermaid/mermaid.min.js" in full
    assert "renderMathInElement" in full      # 公式自动渲染
    assert "language-mermaid" in full         # 围栏代码 → mermaid 图
    # $$ 定界符在 JS 里必须原样保留（Template 会把 $$ 转义成 $）
    assert '{left: "$$"' in full


def test_static_assets_served():
    from mip.browser_server import lookup_static
    katex = lookup_static("katex/katex.min.js")
    assert katex is not None and os.path.isfile(katex)
    assert lookup_static("mermaid/mermaid.min.js") is not None
    # 穿越与哨兵不可达
    assert lookup_static("../__init__.py") is None
    assert lookup_static(".ok") is None
    assert lookup_static("nope.js") is None


def test_static_route_http(server):
    resp, conn = _get(server.base_url, "/static/katex/katex.min.js")
    body = resp.read()
    conn.close()
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "text/javascript"
    assert len(body) > 100000  # katex.min.js ~270KB
    resp, conn = _get(server.base_url, "/static/../mip/__init__.py")
    assert resp.status == 404
    conn.close()


def test_page_title_named_and_pushed(server):
    server.set_page("d1", "<p>1</p>", title="Preview README.md")
    resp, conn = _get(server.base_url, "/d1")
    assert "<title>Preview README.md</title>" in resp.read().decode()
    conn.close()
    # 标题变化经 "t" 帧推送（document.title 直接赋值，无需重发整页）
    conn, read_event = _open_sse(server, "d1")
    assert "h" in read_event()  # 注册即补推快照
    server.set_page("d1", "<p>2</p>", title="Preview CHANGELOG.md")
    assert read_event()["t"] == "Preview CHANGELOG.md"
    conn.close()
