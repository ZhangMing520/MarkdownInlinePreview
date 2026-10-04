"""markdown-it-py 引擎（v0.2 可选）。

纯 Python，MIT，vendor 进 mip/vendor/（含其依赖 mdurl 与 mdit-py-plugins）。
CommonMark 还原度最高，配合 mdit-py-plugins 提供 GFM 表格 / 任务列表 / 删除线——
这些正是 python-markdown 默认扩展缺失、需额外扩展才能补齐的能力。
front matter 由 mip.render 统一在引擎前抽取，不在此装配对应插件。

版本：vendored markdown-it-py 4.2.0 + mdit-py-plugins 0.6.1 + mdurl 0.1.2，
要求 Python 3.10+（ST Build 4213+ 的 3.14 宿主）。旧构建（3.8 宿主）下导入会抛
SyntaxError（PEP 604 注解等）或 TypeError（collections.abc ABC 运行时下标，
3.8 实测为 "'ABCMeta' object is not subscriptable"）——由 engines 注册层在
懒加载/构造阶段统一捕获并优雅回落到 python-markdown，本模块不要在 3.8 下被提前
顶层 import（见 __init__.py 的 _ENGINE_LOAD_ERRORS）。
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
        # "default" preset（对应 JS markdown-it 默认档）自带 GFM 表格 + 删除线(~x~)
        # （4.x 的 preset 声明为空 components，但规则在构造期默认 enable，已实测）；
        # 不使用 0.6 的 gfm 聚合插件——它捆绑脚注/alerts/裸链接 autolink，会改变输出。
        # html=True 与 python-markdown 引擎行为对齐（允许内联原始 HTML）；
        # linkify=False：linkify-it-py 不 vendor，自动链接交给 GFM 的尖括号语法；
        # anchors 给标题生成 id（预览内 #锚点 跳转依赖；python-markdown 引擎用 toc 扩展；
        # 该插件默认只覆盖 h1/h2，新旧版一致，保持无参）
        self._md = (
            MarkdownIt("default", {"html": True, "linkify": False})
            .use(tasklists_plugin)
            .use(anchors_plugin)
        )

    def render(self, text: str, settings: dict) -> str:
        return self._md.render(text)
