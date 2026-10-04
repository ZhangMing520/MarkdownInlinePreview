"""completions.py — v0.3 编辑增强。

- 路径补全：在 Markdown 源视图里输入 `](` / `![` 后触发，列出同目录文件/子目录作链接路径。
- 粘贴 URL 自动链接：mip_paste_url_as_link 命令，把选中文字包成 [文字](剪贴板URL)，
  无选中则插入 [URL](URL)。
"""

import logging
import os
import sublime
import sublime_plugin

from .preview import is_preview_view

logger = logging.getLogger("MarkdownInlinePreview")


def _is_markdown(view):
    return "markdown" in view.settings().get("syntax", "").lower()


def _in_link_path_context(view, loc):
    before = view.substr(sublime.Region(view.line(loc).begin(), loc))
    p = before.rfind("](")
    if p == -1:
        return False
    after = before[p + 2:]
    return ")" not in after  # 还没输闭合右括号 → 正在输入路径


class MipPathCompletion(sublime_plugin.EventListener):
    def on_query_completions(self, view, prefix, locations):
        if is_preview_view(view):
            return None
        if not _is_markdown(view) or view.file_name() is None:
            return None
        if not any(_in_link_path_context(view, loc) for loc in locations):
            return None

        base = os.path.dirname(view.file_name())
        completions = []
        try:
            names = sorted(os.listdir(base))
        except OSError:
            logger.debug("路径补全：目录不可读 %s", base)
            return None
        for name in names:
            if name.startswith("."):
                continue
            full = os.path.join(base, name)
            rel = name + "/" if os.path.isdir(full) else name
            completions.append((rel, rel))
        # 带 INHIBIT 标志：不与 ST 默认词补全混合，也不触发公共前缀自动插入
        return completions, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS


class MipPasteUrlAsLinkCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        url = sublime.get_clipboard().strip()
        if not url:
            return
        for region in self.view.sel():
            if region.empty():
                self.view.insert(edit, region.begin(), "[%s](%s)" % (url, url))
            else:
                text = self.view.substr(region)
                self.view.replace(edit, region, "[%s](%s)" % (text, url))
