"""preview.py — toggle 命令 + 预览视图管理（分栏 / 空白预览视图 / 逐块 phantom / 还原布局）。

只碰 Sublime API；纯 Python 的渲染逻辑在 mip.render。本模块无法在无 Sublime 环境运行，
仅能做导入冒烟测试（见 tests/test_import_smoke.py），行为需在 Sublime 内验证。
"""

import logging
import os
import sublime
import sublime_plugin

from .engines import get_engine
from . import settings as mip_settings
from .render import DEFAULT_STYLE, render_html, split_blocks

logger = logging.getLogger("MarkdownInlinePreview")

# 预览视图的内部标记（settings 里打这个 tag，用于识别预览视图、避免误伤普通视图）
PREVIEW_SETTINGS_KEY = "mip_preview"

# 每窗口维护一个预览管理器（plan：一个窗口只一个预览，绑定源视图）
_MANAGERS = {}


# listener.py / settings.py 通过这些函数访问管理器，不直接碰私有 dict
def get_manager(window_id):
    return _MANAGERS.get(window_id)


def forget_manager(window_id):
    _MANAGERS.pop(window_id, None)


def each_manager():
    return list(_MANAGERS.values())


class _MipSetTextCommand(sublime_plugin.TextCommand):
    """内部命令：用 edit 重写预览视图文本（phantom 需要每块的占位行）。"""

    def run(self, edit, text):
        self.view.replace(edit, sublime.Region(0, self.view.size()), text)


class PreviewManager:
    def __init__(self, window):
        self.window = window
        self.source = None
        self.view = None
        self._orig_layout = None
        self._orig_group = 0
        self._keys = []
        # 防抖代际：sublime.set_timeout 无法取消，旧 timer 靠比对 gen 自行失效
        self._gen = 0

    # -- 生命周期 ----------------------------------------------------------

    def is_open(self):
        return self.view is not None and self.view.is_valid()

    def is_source(self, view):
        return view is not None and self.source is not None and self.source.id() == view.id()

    def is_preview(self, view):
        return view is not None and self.view is not None and self.view.id() == view.id()

    def open(self):
        source = self.window.active_view()
        if source is None:
            return
        self.source = source
        self._orig_layout = self.window.get_layout()
        self._orig_group = self.window.active_group()

        # 两栏布局
        self.window.set_layout({
            "cols": [0.0, 0.5, 1.0],
            "rows": [0.0, 1.0],
            "cells": [[0, 0, 1, 1], [1, 0, 2, 1]],
        })
        # 在右栏开空白预览视图
        self.window.focus_group(1)
        pv = self.window.new_file()
        self.window.focus_view(source)
        self._configure_view(pv)
        self.view = pv
        self.render()

    def _configure_view(self, pv):
        pv.set_scratch(True)                       # 关 tab 不弹保存
        pv.set_read_only(True)                     # 防在预览里打字
        pv.settings().set(PREVIEW_SETTINGS_KEY, True)
        pv.set_syntax_file("Packages/Text/Plain text.tmLanguage")  # 专用隐藏 syntax
        pv.settings().set("line_numbers", False)
        pv.settings().set("gutter", False)

    def close(self):
        # 先注销 manager 再关视图：视图关闭会触发 listener 的 on_close，
        # 此时 manager 已不在 _MANAGERS，避免重复还原/自引用
        forget_manager(self.window.id())
        if self.is_open():
            self._erase_phantoms()
            self.view.close()
        self.view = None
        self.restore_layout()

    def restore_layout(self):
        if self._orig_layout is not None:
            try:
                self.window.set_layout(self._orig_layout)
                self.window.focus_group(self._orig_group)
            except Exception:
                logger.exception("MarkdownInlinePreview: 还原窗口布局失败")

    # -- 渲染（逐块 phantom）-----------------------------------------------

    def schedule_render(self):
        cfg = mip_settings.get_settings()
        delay = cfg.get("refresh_delay_ms", 300)
        self._gen += 1
        gen = self._gen

        def _go():
            # set_timeout 不可取消：只有最后一次 schedule 的 gen 仍为最新才渲染
            if gen != self._gen:
                return
            self.render()

        sublime.set_timeout(_go, delay)

    def render(self):
        if not self.is_open() or self.source is None or not self.source.is_valid():
            return
        cfg = mip_settings.get_settings()
        engine, msg = get_engine(cfg.get("engine", "python-markdown"))
        if msg:
            sublime.status_message("MarkdownInlinePreview: " + msg)
        if engine is None:
            return
        text = self.source.substr(sublime.Region(0, self.source.size()))
        base_dir = os.path.dirname(self.source.file_name()) if self.source.file_name() else None
        try:
            html = render_html(text, cfg, engine, base_dir=base_dir)
        except Exception:
            logger.exception("MarkdownInlinePreview: 渲染失败，预览保持旧内容")
            sublime.status_message("MarkdownInlinePreview: 渲染失败，详见控制台")
            return
        self._update_phantoms(split_blocks(html))

    def _update_phantoms(self, blocks):
        view = self.view
        self._erase_phantoms()
        view.set_read_only(False)
        view.run_command("_mip_set_text", {"text": "\n" * max(len(blocks) - 1, 0)})
        new_keys = []
        for i, blk in enumerate(blocks):
            key = "mip_block_%d" % i
            # 每个 phantom 是独立 minihtml 文档，逐块前置样式
            view.add_phantom(key, view.line(i), DEFAULT_STYLE + blk, sublime.LAYOUT_BLOCK, on_navigate=self._on_navigate)
            new_keys.append(key)
        view.set_read_only(True)
        self._keys = new_keys

    def _erase_phantoms(self):
        if self.view is None:
            return
        for k in self._keys:
            self.view.erase_phantom(k)
        self._keys = []

    # -- 交互 --------------------------------------------------------------

    def _on_navigate(self, href):
        if href.startswith(("http://", "https://")):
            import webbrowser
            webbrowser.open(href)
        elif href.startswith("#"):
            # v0.2：文内锚点 #heading → 定位对应块并 view.show()
            pass

    def sync_scroll(self, source):
        # 块级近似对齐：源光标行按比例映射到预览对应块（非像素级）
        if not self.is_open() or not source.sel():
            return
        row, _ = source.rowcol(source.sel()[0].begin())
        total = source.line_count() or 1
        blocks = len(self._keys) or 1
        target = min(int(row / total * blocks), blocks - 1)
        try:
            self.view.show(self.view.line(target), True)
        except Exception:
            pass


class MipTogglePreviewCommand(sublime_plugin.WindowCommand):
    def run(self):
        wid = self.window.id()
        mgr = get_manager(wid)
        if mgr is not None and mgr.is_open():
            same_source = mgr.is_source(self.window.active_view())
            # 先关掉旧预览（含还原布局），避免切到别的文件后旧预览视图被孤立
            mgr.close()
            if same_source:
                return  # 同一源视图 → toggle 语义：关闭即止
        mgr = PreviewManager(self.window)
        _MANAGERS[wid] = mgr
        mgr.open()


def plugin_loaded():
    # 清理上次插件 reload 遗留的孤儿预览视图（开发期频繁 reload 必然产生）
    closed = 0
    for w in sublime.windows():
        for v in w.views():
            if v.settings().get(PREVIEW_SETTINGS_KEY, False):
                v.close()
                closed += 1
    if closed:
        logger.info("MarkdownInlinePreview: 清理了 %d 个遗留预览视图", closed)


def plugin_unloaded():
    for mgr in each_manager():
        try:
            mgr.restore_layout()
        except Exception:
            logger.exception("MarkdownInlinePreview: 卸载时还原布局失败")
    _MANAGERS.clear()
