"""preview.py — toggle 命令 + 预览视图管理（分栏 / 空白预览视图 / 逐块 phantom / 还原布局）。

只碰 Sublime API；纯 Python 的渲染逻辑在 mip.render。本模块无法在无 Sublime 环境运行，
仅能做导入冒烟测试（见 tests/test_import_smoke.py），行为需在 Sublime 内验证。
"""

import logging
import os
import re

import sublime
import sublime_plugin

from . import async_render
from .engines import get_engine
from . import settings as mip_settings
from .render import DEFAULT_STYLE, render_html, split_blocks

logger = logging.getLogger("MarkdownInlinePreview")

# 预览视图的内部标记（settings 里打这个 tag，用于识别预览视图、避免误伤普通视图）
PREVIEW_SETTINGS_KEY = "mip_preview"

# minihtml 的 white-space: pre-wrap 需要 Build 4170+（官方文档）；模块在主线程加载，
# 此处一次性读 version，供后台渲染任务决定代码块走原生 <pre> 还是 div 降级
_PRE_WRAP_SUPPORTED = int(sublime.version() or 0) >= 4170


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


def target_block(ratio, blocks):
    """光标比例（0~1）→ 预览块序号（0..blocks-1）。"""

    return min(int(ratio * blocks), blocks - 1)


def proportional_y(target, blocks, max_y):
    """块序号 → 按比例的布局 y 坐标（块高等高假设，块级近似的兜底映射）。"""

    if blocks <= 1:
        return 0.0
    return max_y * target / (blocks - 1)


def preview_title(source):
    """预览标题（VS Code 惯例 "Preview <文件名>"），内嵌标签页与浏览器页面共用。

    未落盘文件取缓冲区显示名（View.name()，可被用户改），避免多个预览/标签都显示
    "未命名" 或 scratch 默认的 "untitled" 而无法区分。
    """

    name = source.file_name() or source.name()
    return "Preview " + (os.path.basename(name) if name else "未命名")


def status_message(msg):
    """统一状态栏前缀，内嵌/浏览器两种预览共用（避免前缀字面量在各处重复、str()/msg 漂移）。"""

    sublime.status_message("MarkdownInlinePreview: " + str(msg))


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

# 每窗口维护多个预览管理器：window_id → {source_view_id: PreviewManager}。
# 与浏览器模式一致按源视图隔离——右栏（group 1）里每个源视图对应一个预览标签页，
# 同一窗口可同时开任意多个；布局只在首个预览打开时切两栏、末个关闭时还原。
_MANAGERS = {}

# 窗口 → 打开首个预览前的原始布局/活动分栏（末个预览关闭时还原）
_ORIG_LAYOUTS = {}

# 预览恒在右栏（group 1）：切栏布局、开标签的 focus_group、标签跟随都以此为准
PREVIEW_GROUP = 1

_SPLIT_LAYOUT = {
    "cols": [0.0, 0.5, 1.0],
    "rows": [0.0, 1.0],
    "cells": [[0, 0, 1, 1], [1, 0, 2, 1]],
}

# listener.py / settings.py / toggle 命令通过这些函数访问管理器，不直接碰私有 dict
def get_managers(window_id):
    """该窗口全部内嵌预览管理器。"""

    return list(_MANAGERS.get(window_id, {}).values())


def manager_for_view(window_id, view):
    """按源视图或预览视图反查管理器，没有则 None。"""

    per_window = _MANAGERS.get(window_id)
    if not per_window or view is None:
        return None
    # 注册表按源视图 id 建键，源视图 O(1) 直取；视图 id 全局唯一，
    # 预览视图 id 不会撞键，故落空后再按预览视图线性反查
    mgr = per_window.get(view.id())
    if mgr is not None:
        return mgr
    for candidate in per_window.values():
        if candidate.is_preview(view):
            return candidate
    return None


def add_manager(window_id, source_id, mgr):
    _MANAGERS.setdefault(window_id, {})[source_id] = mgr


def remove_manager(window_id, source_id):
    per_window = _MANAGERS.get(window_id)
    if not per_window:
        return None
    mgr = per_window.pop(source_id, None)
    if not per_window:
        _MANAGERS.pop(window_id, None)
    return mgr


def each_manager():
    return [mgr for per_window in _MANAGERS.values() for mgr in per_window.values()]


def forget_window(window_id):
    _MANAGERS.pop(window_id, None)
    _ORIG_LAYOUTS.pop(window_id, None)


def ensure_split_layout(window):
    """首个预览打开时保存原布局并切两栏；已有预览则不动布局。"""

    wid = window.id()
    if wid not in _ORIG_LAYOUTS:
        _ORIG_LAYOUTS[wid] = (window.get_layout(), window.active_group())
        window.set_layout(_SPLIT_LAYOUT)


def restore_layout_if_last(window):
    """该窗口已无预览时还原原始布局。"""

    if _MANAGERS.get(window.id()):
        return
    saved = _ORIG_LAYOUTS.pop(window.id(), None)
    if saved is None:
        return
    layout, group = saved
    try:
        window.set_layout(layout)
        window.focus_group(group)
    except Exception:
        logger.exception("MarkdownInlinePreview: 还原窗口布局失败")


def close_manager(mgr, close_view=True):
    """统一关闭路径（toggle/源视图关闭/预览标签手动关闭共用）：

    先从注册表摘除（视图关闭触发 on_close 时已查不到本 manager，避免重入），
    再按需擦 phantom、关视图；窗口内一个预览都不剩时还原布局。
    close_view=False 用于"预览标签本身正在关闭"的 on_close 路径（不能再 close 它）。
    """

    wid = mgr.window.id()
    if mgr.source is not None:
        remove_manager(wid, mgr.source.id())
    if close_view and mgr.is_open():
        mgr.erase_phantoms()
        mgr.view.close()
    mgr.view = None
    restore_layout_if_last(mgr.window)


class MipSetTextCommand(sublime_plugin.TextCommand):
    """内部命令：用 edit 重写预览视图文本（phantom 需要每块的占位行）。

    必须在根模块 MarkdownInlinePreview.py 显式导入，否则 Sublime 不注册、
    run_command 静默空转，phantom 全挂点 0、同步滚动恒定位顶部
    （详见 CHANGELOG 2026-10-04；tests/test_command_registration.py 钉死该耦合）。
    """

    def run(self, edit, text):
        self.view.replace(edit, sublime.Region(0, self.view.size()), text)


class PreviewManager:
    def __init__(self, window, source):
        self.window = window
        self.source = source
        self.view = None
        # 上次渲染的原始块列表：增量更新用它差分（phantom 数 = len，无需另存 key 列表），
        # 未变的块原地保留，避免全量重插的闪烁
        self._last_blocks = None
        self._last_sync_target = None
        # 元素 id → 块序号，#锚点 跳转用
        self._anchors = {}
        # 防抖代际（schedule_debounced 用）
        self._gen = 0
        # 后台渲染代际：每次投递 +1，过期结果回主线程时比对丢弃
        self._render_gen = 0
        # sync_scroll 挂在每次光标移动上，持续性失败只记一次完整 traceback
        self._scroll_failed_logged = False
        # 坐标不可用退回比例映射是异常信号（phantom 全挂点 0 即此形态），只告警一次
        self._scroll_fallback_logged = False

    # -- 生命周期 ----------------------------------------------------------

    def is_open(self):
        return self.view is not None and self.view.is_valid()

    def is_source(self, view):
        return view is not None and self.source is not None and self.source.id() == view.id()

    def is_preview(self, view):
        return view is not None and self.view is not None and self.view.id() == view.id()

    def open(self):
        # 布局由窗口级协调：首个预览切两栏，其后只在右栏追加标签页
        ensure_split_layout(self.window)
        # 在右栏开空白预览视图（右栏已有预览时，new_file 自动成为新标签页）
        self.window.focus_group(PREVIEW_GROUP)
        pv = self.window.new_file()
        self._configure_view(pv)
        pv.set_name(preview_title(self.source))
        self.view = pv
        # 还焦点给源视图（这次激活不会触发跟随：右栏前台已是对应预览，listener 有判定）
        self.window.focus_view(self.source)
        self.render()

    def close(self):
        # 统一走模块级关闭路径（注销/关视图/末个还原布局）
        close_manager(self)

    def _configure_view(self, pv):
        pv.set_scratch(True)                       # 关 tab 不弹保存
        pv.set_read_only(True)                     # 防在预览里打字
        pv.settings().set(PREVIEW_SETTINGS_KEY, True)
        pv.set_syntax_file("Packages/Text/Plain text.tmLanguage")  # 专用隐藏 syntax
        pv.settings().set("line_numbers", False)
        pv.settings().set("gutter", False)
        # 压缩块间空隙：每个块独占一个空行作为 phantom 锚点（见 _update_phantoms 的 "\n"
        # 占位缓冲），空行默认行盒约 19px，是块间唯一的间距来源。负行 padding 只压得动
        # 空锚点行——phantom 自身内容行盒会被内容最小高度钳住不受影响；同步滚动取
        # text_to_layout 真实坐标，压缩后定位仍精确。-2px 为真机微调值（贴近 GitHub
        # 16px 块距），若 Sublime 调整行盒算法在此一并改。
        pv.settings().set("line_padding_top", -2)
        pv.settings().set("line_padding_bottom", -2)

    # -- 渲染（逐块 phantom）-----------------------------------------------

    def schedule_render(self):
        delay = mip_settings.get_settings().get("refresh_delay_ms", 300)
        schedule_debounced(self, delay, self.render)

    def render(self):
        if not self.is_open() or self.source is None or not self.source.is_valid():
            return
        cfg = mip_settings.get_settings()
        # ST API 调用留在主线程：取源文本（view.substr 只能主线程），之后整段渲染
        # （引擎转换 + 图片 base64 文件 IO + minihtml 适配）移到后台单线程，不卡输入
        text, base_dir = read_source(self.source)
        self._render_gen += 1
        gen = self._render_gen
        engine_name = cfg["engine"]

        def _job():
            # 引擎单例首次构建（import/vendor 解压）也在后台完成，属一次性开销
            engine, msg = get_engine(engine_name)
            if engine is None:
                return None, msg
            return render_html(text, cfg, engine, base_dir=base_dir,
                               pre_wrap=_PRE_WRAP_SUPPORTED), msg

        def _ok(payload):
            if gen != self._render_gen or not self.is_open():
                return  # 更新的渲染已投递，或预览在渲染期间被关闭
            html, msg = payload
            if html is None:
                status_message(msg)
                return
            if msg:
                status_message(msg)
            self._update_phantoms(split_blocks(html))

        def _fail(exc):
            if gen != self._render_gen or not self.is_open():
                return
            logger.exception("MarkdownInlinePreview: 渲染失败，预览保持旧内容")
            status_message("渲染失败，详见控制台")

        async_render.submit(self, _job, _ok, _fail)

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
            self.erase_phantoms()
            view.set_read_only(False)
            view.run_command("mip_set_text", {"text": "\n" * max(len(blocks) - 1, 0)})
            for i, blk in enumerate(blocks):
                self._add_phantom(i, DEFAULT_STYLE + blk)
            view.set_read_only(True)
        self._last_blocks = blocks
        # 块高度可能已变，作废跨块去重缓存：光标不动也要允许下次事件重新定位
        self._last_sync_target = None

    def _add_phantom(self, i, content):
        # 每个 phantom 是独立 minihtml 文档，逐块前置样式（content 已含 DEFAULT_STYLE）
        self.view.add_phantom(
            "mip_block_%d" % i, self.view.line(i), content,
            sublime.LAYOUT_BLOCK, on_navigate=self._on_navigate
        )

    def _erase_phantom(self, i):
        self.view.erase_phantoms("mip_block_%d" % i)

    def _update_anchors(self, blocks):
        anchors = {}
        for i, blk in enumerate(blocks):
            for elem_id in _ID_RE.findall(blk):
                anchors.setdefault(elem_id, i)
        self._anchors = anchors

    def erase_phantoms(self):
        if self.view is None:
            return
        # phantom 与 _last_blocks 一一对应（key 按序号生成），无需另存 key 列表
        for i in range(len(self._last_blocks or ())):
            self.view.erase_phantoms("mip_block_%d" % i)

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

    # -- 同步滚动 ----------------------------------------------------------

    def sync_scroll(self, source):
        # 块级近似对齐：源光标行按比例映射到预览块，再取该块占位行的真实布局坐标定位
        # （坐标含此前各块 phantom 撑起的高度，非像素级但对应真实内容位置；plan v0.2）。
        # 定位必须显式 animate=False：后台视图上动画不播放，旧代码在动画起点读回坐标再写回，
        # 结果永远停在顶部（详见 CHANGELOG 2026-10-04）。
        if not self.is_open() or not source.sel():
            return
        blocks = len(self._last_blocks) or 1
        target = target_block(cursor_ratio(source), blocks)
        if target == self._last_sync_target:
            return  # 跨块才滚：同块内移动光标不重复定位
        self._last_sync_target = target
        self._scroll_to_block(target, blocks)

    def _scroll_to_block(self, target, blocks):
        # 宿主 API 调用全部进防护：本方法在 listener 的逐 manager 循环里跑，
        # 未捕获异常会连带中断浏览器预览的同步滚动
        try:
            preview = self.view
            max_y = max(0.0, float(preview.layout_extent()[1])
                        - float(preview.viewport_extent()[1]))
            line = preview.line(target)
            raw_y = float(preview.text_to_layout(line.begin())[1]) if line else -1.0
            # 正常路径：每块挂在自己的占位行，坐标即真实位置（含前块 phantom 撑高）。
            # raw_y 不可用（≤0）时退化为按块序号比例映射；两分支结果恒 ≥0，无需再夹取。
            if raw_y > 0.0:
                y = min(raw_y, max_y)
            else:
                if target > 0 and not self._scroll_fallback_logged:
                    self._scroll_fallback_logged = True
                    logger.warning("同步滚动坐标不可用（target 块=%d），退回比例映射；"
                                   "若持续定位顶部，检查 mip_set_text 是否已注册", target)
                y = proportional_y(target, blocks, max_y)
            preview.set_viewport_position((0.0, y), False)
        except Exception:
            # 不能静默：本方法此前静默失效数周才被发现，首次完整 traceback、后续降 debug
            if not self._scroll_failed_logged:
                self._scroll_failed_logged = True
                logger.exception("同步滚动定位失败（target 块=%d）", target)
            else:
                logger.debug("同步滚动定位失败（target 块=%d）", target)


class MipTogglePreviewCommand(sublime_plugin.WindowCommand):
    def run(self):
        source = self.window.active_view()
        if source is None:
            return
        wid = self.window.id()
        # toggle 语义按源视图：该文件的预览已开 → 只关它（最后一个时还原布局）；
        # 没开 → 在右栏追加该文件的预览标签页，不影响其它已开预览
        mgr = manager_for_view(wid, source)
        if mgr is not None and mgr.is_open():
            mgr.close()
            return
        mgr = PreviewManager(self.window, source)
        add_manager(wid, source.id(), mgr)
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
    # 先取管理器再清空注册表：清空后 restore_layout_if_last 的"窗口仍有预览"判定不拦，
    # 同窗多管理器时首个即还原并弹出保存布局，其余为空操作（无需再去重）
    managers = each_manager()
    _MANAGERS.clear()
    for mgr in managers:
        restore_layout_if_last(mgr.window)
    _ORIG_LAYOUTS.clear()
