"""listener.py — 监听源视图与预览视图。

- 源视图：on_modified_async 防抖刷新、on_selection_modified_async 同步滚动、
  on_activated_async 右栏预览标签自动跟随
- 关闭：ViewEventListener 收不到 on_close（ST 只在 EventListener 上派发），
  故 on_close 用全局 EventListener，按 view id 区分源视图 / 预览视图。
"""

import logging

import sublime_plugin

from . import browser as browser_mod
from . import preview as preview_mod
from . import settings as mip_settings

logger = logging.getLogger("MarkdownInlinePreview")


class MipSourceListener(sublime_plugin.ViewEventListener):
    """只监听源 Markdown 视图（预览视图本身排除）。"""

    @classmethod
    def is_applicable(cls, view):
        return not preview_mod.is_preview_view(view)

    def _managers(self):
        """本视图可能关联的两种预览管理器（minihtml 内嵌 + 浏览器实时）。"""

        window = self.view.window()
        if window is None:
            return ()
        wid = window.id()
        # 内嵌预览按源视图多开，取该窗口全部管理器（循环里再按 is_source 过滤）；
        # 浏览器预览按源视图 id 注册，直查即得
        bm = browser_mod.manager_for_source(wid, self.view)
        return tuple(preview_mod.get_managers(wid)) + ((bm,) if bm is not None else ())

    def on_activated_async(self):
        # 标签跟随：源文件标签激活时，把右栏切到它对应的预览标签
        if not mip_settings.get_settings().get("preview_tab_follows_source", True):
            return
        window = self.view.window()
        if window is None:
            return
        mgr = preview_mod.manager_for_view(window.id(), self.view)
        if mgr is None or not mgr.is_source(self.view) or not mgr.is_open():
            return
        # 右栏前台已是对应预览就不切（focus_view 会抢焦点：否则点回源视图又被拉去右栏，
        # 且打开预览还焦点触发的那次激活同样被这一条挡住）
        if window.active_view_in_group(preview_mod.PREVIEW_GROUP) == mgr.view:
            return
        window.focus_view(mgr.view)

    def on_modified_async(self):
        for mgr in self._managers():
            if mgr.is_source(self.view):
                mgr.schedule_render()

    def on_selection_modified_async(self):
        if not mip_settings.get_settings().get("sync_scroll", True):
            return
        for mgr in self._managers():
            if mgr.is_source(self.view):
                mgr.sync_scroll(self.view)


class MipCloseListener(sublime_plugin.EventListener):
    """全局关闭清理：源视图关闭 → 关两种预览；预览视图被手动关闭 → 摘除管理器、
    末个预览关闭时还原布局；窗口关闭 → 兜底注销其全部预览管理器。"""

    def on_close(self, view):
        window = view.window()
        if window is None:
            return
        # 源视图关闭 → 停止该文件的浏览器实时预览（浏览器标签页保留最后内容）
        browser_mod.forget_source(window.id(), view)
        mgr = preview_mod.manager_for_view(window.id(), view)
        if mgr is None:
            return
        if mgr.is_preview(view):
            # 预览标签被手动关闭：视图本身已在关闭流程中，不能再 close()，
            # 只摘除管理器并在窗口内无预览时还原布局
            logger.debug("MarkdownInlinePreview: 预览视图被手动关闭")
            preview_mod.close_manager(mgr, close_view=False)
        elif mgr.is_source(view):
            # 源视图关闭 → 关它的预览并在末个时还原布局
            mgr.close()

    def on_window_close(self, window):
        # 关窗兜底：on_close 逐视图触发不可依赖（触发时 window() 可能已为 None 早退），
        # 按视图注册的浏览器预览若不整体注销会成批泄漏 manager + 服务器文档
        browser_mod.forget_window(window.id())
        preview_mod.forget_window(window.id())
