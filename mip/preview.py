"""preview.py — toggle 命令 + 预览视图管理（分栏 / 空白预览视图 / 逐块 phantom / 还原布局）。

只碰 Sublime API；纯 Python 的渲染逻辑在 mip.render。本模块无法在无 Sublime 环境运行，
仅能做导入冒烟测试（见 tests/test_import_smoke.py），行为需在 Sublime 内验证。
"""

import logging
import os
import re

import sublime
import sublime_plugin

from .engines import get_engine
from . import settings as mip_settings
from .render import DEFAULT_STYLE, render_html, split_blocks

logger = logging.getLogger("MarkdownInlinePreview")

# 预览视图的内部标记（settings 里打这个 tag，用于识别预览视图、避免误伤普通视图）
PREVIEW_SETTINGS_KEY = "mip_preview"


def is_preview_view(view):
    """是否 mip 打开的预览视图。内部 tag 的编码只在这一处，其他模块用它判断。

    宿主兼容：ST 4205+（Python 3.14 宿主）的 ViewEventListener.is_applicable 传入的是
    view.settings() 而非 View。View 有 .settings()、Settings 没有，按此取设置。
    """

    settings = view.settings() if hasattr(view, "settings") else view
    return bool(settings.get(PREVIEW_SETTINGS_KEY, False))


def read_source(view):
    """源视图全文 + 图片基准目录（未落盘文件为 None）。两种预览共用。"""

    text = view.substr(sublime.Region(0, view.size()))
    name = view.file_name()
    return text, (os.path.dirname(name) if name else None)


def cursor_ratio(view):
    """光标行 / 总行数（0~1），两种预览的近似比例定位共用。

    View 没有 line_count()/rowcount()，行数用 rowcol(view.size()) 取最后一行行号 + 1 计算。
    """

    row, _ = view.rowcol(view.sel()[0].begin())
    last_row, _ = view.rowcol(view.size())
    return row / (last_row + 1)


def schedule_debounced(holder, delay_ms, render):
    """代际防抖：sublime.set_timeout 无法取消，旧 timer 靠比对 holder._gen 自行失效。

    preview / browser 两个 manager 共用（各自初始化 _gen = 0）。
    """

    holder._gen += 1
    gen = holder._gen

    def _go():
        # 只有最后一次 schedule 的 gen 仍为最新才渲染
        if gen == holder._gen:
            render()

    sublime.set_timeout(_go, delay_ms)


# 块 HTML 里的元素 id（toc/anchors 扩展生成），供 #锚点 链接跳转定位块
_ID_RE = re.compile(r"""\bid=["']([^"']+)["']""")

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
        # 上次渲染的原始块列表：增量更新用它差分（phantom 数 = len，无需另存 key 列表），
        # 未变的块原地保留，避免全量重插的闪烁
        self._last_blocks = None
        # 元素 id → 块序号，#锚点 跳转用
        self._anchors = {}
        # 防抖代际（schedule_debounced 用）
        self._gen = 0
        # sync_scroll 挂在每次光标移动上，持续性失败只记一次完整 traceback
        self._scroll_failed_logged = False

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
        delay = mip_settings.get_settings().get("refresh_delay_ms", 300)
        schedule_debounced(self, delay, self.render)

    def render(self):
        if not self.is_open() or self.source is None or not self.source.is_valid():
            return
        cfg = mip_settings.get_settings()
        engine, msg = get_engine(cfg.get("engine", "python-markdown"))
        if msg:
            sublime.status_message("MarkdownInlinePreview: " + msg)
        if engine is None:
            return
        text, base_dir = read_source(self.source)
        try:
            html = render_html(text, cfg, engine, base_dir=base_dir)
        except Exception:
            logger.exception("MarkdownInlinePreview: 渲染失败，预览保持旧内容")
            sublime.status_message("MarkdownInlinePreview: 渲染失败，详见控制台")
            return
        self._update_phantoms(split_blocks(html))

    def _update_phantoms(self, blocks):
        view = self.view
        if self._last_blocks is not None and len(self._last_blocks) == len(blocks):
            # 增量：块数不变时只重插内容有变化的块（DEFAULT_STYLE 是常量，diff 原始块即可）
            changed = [i for i, b in enumerate(blocks) if b != self._last_blocks[i]]
            if not changed:
                return
            self._update_anchors(blocks)
            view.set_read_only(False)
            for i in changed:
                self._erase_phantom(i)
                self._add_phantom(i, DEFAULT_STYLE + blocks[i])
            view.set_read_only(True)
        else:
            # 块数变化（或首次）：整版重写占位缓冲与全部 phantom
            self._update_anchors(blocks)
            self._erase_phantoms()
            view.set_read_only(False)
            view.run_command("_mip_set_text", {"text": "\n" * max(len(blocks) - 1, 0)})
            for i, blk in enumerate(blocks):
                self._add_phantom(i, DEFAULT_STYLE + blk)
            view.set_read_only(True)
        self._last_blocks = blocks

    def _add_phantom(self, i, content):
        # 每个 phantom 是独立 minihtml 文档，逐块前置样式（content 已含 DEFAULT_STYLE）
        self.view.add_phantom(
            "mip_block_%d" % i, self.view.line(i), content,
            sublime.LAYOUT_BLOCK, on_navigate=self._on_navigate
        )

    def _erase_phantom(self, i):
        self.view.erase_phantom("mip_block_%d" % i)

    def _update_anchors(self, blocks):
        anchors = {}
        for i, blk in enumerate(blocks):
            for elem_id in _ID_RE.findall(blk):
                anchors.setdefault(elem_id, i)
        self._anchors = anchors

    def _erase_phantoms(self):
        if self.view is None:
            return
        # phantom 与 _last_blocks 一一对应（key 按序号生成），无需另存 key 列表
        for i in range(len(self._last_blocks or ())):
            self.view.erase_phantom("mip_block_%d" % i)

    # -- 交互 --------------------------------------------------------------

    def _on_navigate(self, href):
        if href.startswith(("http://", "https://")):
            import webbrowser
            webbrowser.open(href)
        elif href.startswith("#"):
            # 文内锚点：定位 id 所在块并滚动过去（toc/anchors 扩展负责生成 id）
            idx = self._anchors.get(href[1:])
            if idx is not None:
                try:
                    self.view.show(self.view.line(idx), True)
                except Exception:
                    logger.exception("锚点跳转定位失败: #%s", href[1:])

    def sync_scroll(self, source):
        # 块级近似对齐：源光标行按比例映射到预览对应块（非像素级）
        if not self.is_open() or not source.sel():
            return
        blocks = len(self._last_blocks) or 1
        target = min(int(cursor_ratio(source) * blocks), blocks - 1)
        try:
            self.view.show(self.view.line(target), True)
        except Exception:
            # 不能静默：sync_scroll 曾因 line_count 不存在静默坏掉数周（2026-10-04）。
            # 本方法随每次光标移动触发：首次报完整 traceback，后续降为 debug。
            if self._scroll_failed_logged:
                logger.debug("同步滚动定位失败（target 块=%d）", target)
            else:
                self._scroll_failed_logged = True
                logger.exception("同步滚动定位失败（target 块=%d）", target)


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
            if is_preview_view(v):
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
