"""browser.py — 浏览器实时预览：每窗口一个 manager + toggle 命令。

与 preview.py（minihtml 内嵌预览）互补：渲染复用同一引擎，但跳过 minihtml
标签转换层，产出完整 HTML 由 LiveServer 推给浏览器，渲染能力无限制
（原生表格、KaTeX/mermaid 等 JS 均可用）。本模块依赖 Sublime API，无法单测。
"""

import logging
import threading
import webbrowser

import sublime
import sublime_plugin

from .browser_server import LiveServer
from .render import render_body
from . import preview as preview_mod
from . import settings as mip_settings

logger = logging.getLogger("MarkdownInlinePreview")

# 每窗口一个 manager；doc_id 用 window id，服务器端按窗口隔离页面
_MANAGERS = {}
_SERVER = None
_SERVER_LOCK = threading.Lock()


def get_server():
    global _SERVER
    with _SERVER_LOCK:
        if _SERVER is None:
            _SERVER = LiveServer()
        _SERVER.ensure_started()
        return _SERVER


def shutdown_server():
    global _SERVER
    with _SERVER_LOCK:
        if _SERVER is not None:
            _SERVER.shutdown()
            _SERVER = None


def get_manager(window_id):
    return _MANAGERS.get(window_id)


def forget_manager(window_id):
    mgr = _MANAGERS.pop(window_id, None)
    if mgr is not None:
        mgr.stop()


def each_manager():
    return list(_MANAGERS.values())


class BrowserManager:
    def __init__(self, window):
        self.window = window
        self.source = None
        self.doc_id = "w%d" % window.id()
        # 防抖代际（preview.schedule_debounced 用）
        self._gen = 0

    def is_source(self, view):
        return view is not None and self.source is not None and self.source.id() == view.id()

    def toggle(self, source):
        """已绑定该源且开着 → 停止并返回 False；否则绑定/换源启动并返回 True。"""

        if self.source is not None and self.is_source(source):
            forget_manager(self.window.id())  # forget 内部会 stop
            return False
        self.source = source
        self.render()
        url = get_server().base_url + "/" + self.doc_id
        webbrowser.open(url)
        sublime.status_message("MarkdownInlinePreview: 浏览器实时预览 " + url)
        return True

    def stop(self):
        self.source = None
        # 服务器可能已被 shutdown（插件卸载），不要再把它拉起来
        with _SERVER_LOCK:
            if _SERVER is not None:
                _SERVER.remove_page(self.doc_id)

    def schedule_render(self):
        if self.source is None:
            return
        delay = mip_settings.get_settings().get("refresh_delay_ms", 300)
        preview_mod.schedule_debounced(self, delay, self.render)

    def render(self):
        from .engines import get_engine

        if self.source is None or not self.source.is_valid():
            return
        cfg = mip_settings.get_settings()
        engine, msg = get_engine(cfg.get("engine", "python-markdown"))
        if engine is None:
            sublime.status_message("MarkdownInlinePreview: " + str(msg))
            return
        text, base_dir = preview_mod.read_source(self.source)
        try:
            body = render_body(text, cfg, engine, base_dir=base_dir)
        except Exception:
            logger.exception("MarkdownInlinePreview: 浏览器预览渲染失败，保持旧页面")
            return
        get_server().set_page(self.doc_id, body, extras=cfg.get("browser_extras", True))

    def sync_scroll(self, source):
        """编辑器光标 → 浏览器按整页比例滚动（与 preview.py 同级的近似对齐）。"""

        if self.source is None or not self.is_source(source) or not source.sel():
            return
        if not mip_settings.get_settings().get("sync_scroll", True):
            return
        get_server().push_scroll(self.doc_id, preview_mod.cursor_ratio(source))


class MipToggleBrowserPreviewCommand(sublime_plugin.WindowCommand):
    def run(self):
        source = self.window.active_view()
        # minihtml 内嵌预览视图不是 Markdown 源，不能对其开浏览器预览
        if source is None or preview_mod.is_preview_view(source):
            return
        mgr = get_manager(self.window.id())
        if mgr is None:
            mgr = BrowserManager(self.window)
            _MANAGERS[self.window.id()] = mgr
        mgr.toggle(source)


def plugin_unloaded():
    for mgr in each_manager():
        try:
            mgr.stop()
        except Exception:
            logger.exception("MarkdownInlinePreview: 停止浏览器预览失败")
    _MANAGERS.clear()
    shutdown_server()
