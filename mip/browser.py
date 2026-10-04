"""browser.py — 浏览器实时预览：每源视图一个 manager + toggle 命令。

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

# 注册表：window_id → {source_view_id: BrowserManager}。
# 按源视图隔离（doc_id = "v<视图id>"）：同窗口同时开多个文件的预览互不覆盖，
# 各有独立 URL 与浏览器标签页。minihtml 内嵌模式保持每窗口一个（单分栏语义）。
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


def manager_for_source(window_id, source):
    """该源视图已开的预览，没有则 None。"""

    return _MANAGERS.get(window_id, {}).get(source.id())


def forget_source(window_id, source):
    """停掉并注销指定源视图的预览（toggle 关闭 / 源视图关闭用），返回是否停过。"""

    per_window = _MANAGERS.get(window_id)
    if not per_window:
        return False
    mgr = per_window.pop(source.id(), None)
    if mgr is None:
        return False
    mgr.stop()
    if not per_window:
        _MANAGERS.pop(window_id, None)
    return True


def forget_window(window_id):
    """窗口关闭时停掉其全部预览。"""

    for mgr in _MANAGERS.pop(window_id, {}).values():
        mgr.stop()


def each_manager():
    return [m for per in _MANAGERS.values() for m in per.values()]


class BrowserManager:
    def __init__(self, window, source):
        self.window = window
        self.source = source
        # doc_id 按源视图编：多文件同时预览时各自独立、互不覆盖
        self.doc_id = "v%d" % source.id()
        # 防抖代际（preview.schedule_debounced 用）
        self._gen = 0
        # sync_scroll 挂在每次光标移动上，持续性失败只记一次完整 traceback
        self._scroll_failed_logged = False

    def is_source(self, view):
        return view is not None and self.source is not None and self.source.id() == view.id()

    def start(self):
        """渲染当前内容并在系统浏览器打开（manager 已注册后再调用）。"""

        self.render()
        url = get_server().base_url + "/" + self.doc_id
        webbrowser.open(url)
        sublime.status_message("MarkdownInlinePreview: 浏览器实时预览 " + url)

    def stop(self):
        self.source = None
        # 服务器可能已被 shutdown（插件卸载），不要再把它拉起来
        with _SERVER_LOCK:
            if _SERVER is not None:
                _SERVER.remove_page(self.doc_id)

    def schedule_render(self):
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
        title = preview_mod.preview_title(self.source)
        get_server().set_page(self.doc_id, body, extras=cfg.get("browser_extras", True), title=title)

    def sync_scroll(self, source):
        """编辑器光标 → 浏览器按整页比例滚动（与 preview.py 同级的近似对齐）。

        listener 逐个调用各 manager 的 sync_scroll，这里抛异常会连带终止
        后面的 manager，故自行吞掉（失败形态与 preview.py 一致：只报一次 traceback）。
        """

        # 调用方（listener 按视图 id 查注册表）已保证 source 匹配，无需再验
        if not source.sel():
            return
        try:
            get_server().push_scroll(self.doc_id, preview_mod.cursor_ratio(source))
        except Exception:
            if self._scroll_failed_logged:
                logger.debug("浏览器同步滚动失败")
            else:
                self._scroll_failed_logged = True
                logger.exception("浏览器同步滚动失败，后续降为 debug")


class MipToggleBrowserPreviewCommand(sublime_plugin.WindowCommand):
    def run(self):
        source = self.window.active_view()
        # minihtml 内嵌预览视图不是 Markdown 源，不能对其开浏览器预览
        if source is None or preview_mod.is_preview_view(source):
            return
        wid = self.window.id()
        # toggle 语义按源视图：同一文件再次触发 → 关闭它的预览；
        # 不同文件 → 各开各的（独立 URL，互不覆盖）
        if forget_source(wid, source):
            return
        mgr = BrowserManager(self.window, source)
        _MANAGERS.setdefault(wid, {})[source.id()] = mgr
        mgr.start()


def plugin_unloaded():
    for mgr in each_manager():
        try:
            mgr.stop()
        except Exception:
            logger.exception("MarkdownInlinePreview: 停止浏览器预览失败")
    _MANAGERS.clear()
    shutdown_server()
