"""listener.py — 监听源视图与预览视图。

- 源视图：on_modified_async 防抖刷新、on_selection_modified_async 同步滚动
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
        # 浏览器预览按源视图 id 注册，直查即得，无需扫全窗口
        return tuple(m for m in (preview_mod.get_manager(wid),
                                 browser_mod.manager_for_source(wid, self.view)) if m)

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
    """全局关闭清理：源视图关闭 → 关两种预览；预览视图被手动关闭 → 还原布局；
    窗口关闭 → 兜底注销其全部预览管理器。"""

    def on_close(self, view):
        window = view.window()
        if window is None:
            return
        # 源视图关闭 → 停止该文件的浏览器实时预览（浏览器标签页保留最后内容）
        browser_mod.forget_source(window.id(), view)
        mgr = preview_mod.get_manager(window.id())
        if mgr is None:
            return
        if mgr.is_preview(view):
            # 预览视图被手动关闭（manager.close 会先注销，不会再走到这里）
            logger.debug("MarkdownInlinePreview: 预览视图被手动关闭")
            mgr.restore_layout()
            mgr.view = None
            preview_mod.forget_manager(window.id())
        elif mgr.is_source(view):
            # 源视图关闭 → 关预览并还原布局
            mgr.close()

    def on_window_close(self, window):
        # 关窗兜底：on_close 逐视图触发不可依赖（触发时 window() 可能已为 None 早退），
        # 按视图注册的浏览器预览若不整体注销会成批泄漏 manager + 服务器文档
        browser_mod.forget_window(window.id())
        preview_mod.forget_manager(window.id())
