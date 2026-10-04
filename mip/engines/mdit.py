"""markdown-it-py 引擎（v0.2 可选）。

纯 Python，MIT，vendor 进 mip/vendor/（含其依赖 mdurl 与 mdit-py-plugins）。
CommonMark 还原度最高，配合 mdit-py-plugins 提供 GFM 表格 / 任务列表 / 删除线——
这些正是 python-markdown 默认扩展缺失、需额外扩展才能补齐的能力。
front matter 由 mip.render 统一在引擎前抽取，不在此装配对应插件。
"""

import os
import sys

# 把 vendor 目录临时加入 sys.path，使 markdown_it / mdurl / mdit_py_plugins 可被顶层 import。
# import 完成后立即移除，避免永久遮蔽其他插件的同名顶层模块；
# 已导入包的子模块靠包自己的 __path__ 解析，移除 sys.path 条目不影响后续懒加载。
# mdit.py 位于 mip/engines/，vendor 在 mip/vendor，故取上级目录再拼 vendor
_VENDOR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vendor")
_added = _VENDOR not in sys.path
if _added:
    sys.path.insert(0, _VENDOR)
try:
    from markdown_it import MarkdownIt
    from mdit_py_plugins.gfm import gfm_plugin  # 含 GFM 表格 + 删除线(~x~)
    from mdit_py_plugins.tasklists import tasklists_plugin
finally:
    if _added:
        sys.path.remove(_VENDOR)

from .engine import Engine


class MarkdownItEngine(Engine):
    name = "markdown-it-py"

    def __init__(self):
        # 显式装配 GFM 插件（不依赖 preset，保证表格/任务列表/删除线都在）
        self._md = (
            MarkdownIt("commonmark")
            .use(gfm_plugin)
            .use(tasklists_plugin)
        )

    def render(self, text: str, settings: dict) -> str:
        return self._md.render(text)
