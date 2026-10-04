"""settings.py — 设置读取 + on_settings_change 热更新。"""

import logging

import sublime

logger = logging.getLogger("MarkdownInlinePreview")

_CHANGE_KEYS = ("engine", "extensions", "refresh_delay_ms", "sync_scroll", "browser_extras")

_DEFAULT_EXTENSIONS = [
    "tables", "fenced_code", "sane_lists", "attr_list", "md_in_html", "codehilite",
    "toc", "pymdownx.tasklist", "pymdownx.tilde",
]


def get_settings():
    s = sublime.load_settings("MarkdownInlinePreview.sublime-settings")
    return {
        "engine": s.get("engine", "python-markdown"),
        "extensions": s.get("extensions", _DEFAULT_EXTENSIONS),
        "refresh_delay_ms": s.get("refresh_delay_ms", 300),
        "sync_scroll": s.get("sync_scroll", True),
        "browser_extras": s.get("browser_extras", True),
    }


def plugin_loaded():
    s = sublime.load_settings("MarkdownInlinePreview.sublime-settings")
    for key in _CHANGE_KEYS:
        s.add_on_change(key, _on_change)


_rerender_pending = False


def _on_change():
    # 保存一次设置会按每个变更键各触发一次本回调：合并成一次重渲染
    global _rerender_pending
    if _rerender_pending:
        return
    _rerender_pending = True
    sublime.set_timeout(_rerender, 0)


def _rerender():
    # 设置热更新：重渲染所有已开预览（minihtml 内嵌 + 浏览器实时两种）
    global _rerender_pending
    _rerender_pending = False
    from . import preview as preview_mod
    from . import browser as browser_mod

    managers = list(preview_mod.each_manager()) + list(browser_mod.each_manager())
    for mgr in managers:
        try:
            mgr.render()
        except Exception:
            logger.debug("MarkdownInlinePreview: 设置变更后某预览重渲染失败", exc_info=True)


def plugin_unloaded():
    s = sublime.load_settings("MarkdownInlinePreview.sublime-settings")
    for key in _CHANGE_KEYS:
        s.clear_on_change(key)
