"""markdown-it-py 引擎（v0.2 可选）。

纯 Python，MIT，vendor 进 mip/vendor/（含其依赖 mdurl 与 mdit-py-plugins）。
CommonMark 还原度最高，配合 mdit-py-plugins 提供 GFM 表格 / 任务列表 / 删除线——
这些正是 python-markdown 默认扩展缺失、需额外扩展才能补齐的能力。
front matter 由 mip.render 统一在引擎前抽取，不在此装配对应插件。
"""

from .. import vendor_loader
from .engine import Engine

# 解析并临时激活 vendor 路径：解包安装直接用目录；zip 安装（PC 发布形态）解压到缓存。
# markdown_it / mdurl / mdit_py_plugins 以顶层名绝对 import（markdown_it 内部亦然），
# 无法改走包相对路径，故必须在 sys.path 激活窗口内完成 import。
with vendor_loader.activate():
    from markdown_it import MarkdownIt
    from mdit_py_plugins.anchors import anchors_plugin
    from mdit_py_plugins.tasklists import tasklists_plugin


class MarkdownItEngine(Engine):
    name = "markdown-it-py"

    def __init__(self):
        # "default" preset（对应 JS markdown-it 默认档）自带 GFM 表格 + 删除线(~x~)；
        # 3.8 宿主只能跑 vendored 2.2.0，其生态没有聚合版 gfm 插件（0.6.x 才有，
        # 而 0.6.x 需要 3.9+），任务列表单独装 tasklists。
        # html=True 与 python-markdown 引擎行为对齐（允许内联原始 HTML）；
        # linkify=False：linkify-it-py 不 vendor，自动链接交给 GFM 的尖括号语法；
        # anchors 给标题生成 id（预览内 #锚点 跳转依赖；python-markdown 引擎用 toc 扩展）
        self._md = (
            MarkdownIt("default", {"html": True, "linkify": False})
            .use(tasklists_plugin)
            .use(anchors_plugin)
        )

    def render(self, text: str, settings: dict) -> str:
        return self._md.render(text)
