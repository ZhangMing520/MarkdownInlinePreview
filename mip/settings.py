"""settings.py — 设置读取 + on_settings_change 热更新。"""

import logging

import sublime

logger = logging.getLogger("MarkdownInlinePreview")

_CHANGE_KEYS = ("engine", "extensions", "refresh_delay_ms", "sync_scroll")

_DEFAULT_EXTENSIONS = [
    "tables", "fenced_code", "sane_lists", "attr_list", "md_in_html", "codehilite"
]


def get_settings():
    s = sublime.load_settings("MarkdownInlinePreview.sublime-settings")
    return {
        "engine": s.get("engine", "python-markdown"),
        "extensions": s.get("extensions", _DEFAULT_EXTENSIONS),
        "refresh_delay_ms": s.get("refresh_delay_ms", 300),
        "sync_scroll": s.get("sync_scroll", True),
    }


def plugin_loaded():
    s = sublime.load_settings("MarkdownInlinePreview.sublime-settings")
    for key in _CHANGE_KEYS:
        s.add_on_change(key, _on_change)


def _on_change():
    # 设置热更新：重渲染所有已开预览
    from . import preview as preview_mod
    for mgr in preview_mod.each_manager():
        try:
            mgr.render()
        except Exception:
            logger.debug("MarkdownInlinePreview: 设置变更后某预览重渲染失败", exc_info=True)


def plugin_unloaded():
    s = sublime.load_settings("MarkdownInlinePreview.sublime-settings")
    for key in _CHANGE_KEYS:
        s.clear_on_change(key)
