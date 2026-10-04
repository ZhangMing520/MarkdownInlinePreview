import sublime
import sublime_plugin

# 让 `mip` 成为本插件包的子包（MarkdownInlinePreview.mip），而非顶层模块——
# Sublime 的插件宿主只会扫描插件包名空间下的模块来注册命令/监听器，顶层 `mip.*`
# 里的命令类不会被发现。测试里 mip 以顶层包导入，故用 __package__ 区分两种情况。
if __package__:
    from .mip import async_render, browser, preview, settings, completions
    # 把命令/监听器类显式带进根模块命名空间：Sublime 主要扫描被直接加载的插件
    # 模块（本文件）的 dir() 来发现命令类；子模块里的类即便已定义，若没出现在
    # 这里也可能不被注册。显式导入后命令面板/快捷键/监听器都能正常工作。
    from .mip.preview import MipTogglePreviewCommand, MipSetTextCommand
    from .mip.browser import MipToggleBrowserPreviewCommand
    from .mip.listener import MipSourceListener, MipCloseListener
    from .mip.completions import MipPasteUrlAsLinkCommand
else:
    from mip import async_render, browser, preview, settings, completions
    from mip.preview import MipTogglePreviewCommand, MipSetTextCommand
    from mip.browser import MipToggleBrowserPreviewCommand
    from mip.listener import MipSourceListener, MipCloseListener
    from mip.completions import MipPasteUrlAsLinkCommand


def plugin_loaded():
    settings.plugin_loaded()
    preview.plugin_loaded()
    # 状态栏确认：重启后若看到这条，说明包已激活（命令未注册的报错不会出现在启动日志里）
    sublime.status_message("MarkdownInlinePreview 已激活")


def plugin_unloaded():
    settings.plugin_unloaded()
    preview.plugin_unloaded()
    browser.plugin_unloaded()
    # 最后停后台渲染线程：排队任务丢弃，在途任务的回调会因预览视图失效被自行挡住
    async_render.shutdown()
