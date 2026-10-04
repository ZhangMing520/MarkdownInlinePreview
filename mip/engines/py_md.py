import markdown

from .. import vendor_loader
from .engine import Engine

# 默认引擎缺的 GFM 能力由 vendored pymdownx 子集补齐（任务列表/删除线）。
# 注意 "pymdownx.tilde" 的 GFM 形态：~~x~~ → <del>（默认 smart 模式关，与 GitHub 一致）
_GFM_EXTS = {"pymdownx.tasklist", "pymdownx.tilde"}


class PythonMarkdownEngine(Engine):
    """默认引擎：python-markdown（PC 依赖频道现成有）+ vendored pymdownx 子集。

    Markdown 对象按 extensions 复用（构建解析器开销大）；
    convert() 不会自动重置状态（链接引用定义会跨文档泄漏），必须逐次 reset()。
    """

    name = "python-markdown"

    def __init__(self):
        self._md = None
        self._exts_key = None

    def render(self, text: str, settings: dict) -> str:
        exts_key = tuple(settings.get("extensions", []))
        if self._md is None or exts_key != self._exts_key:
            with vendor_loader.activate():
                # pymdownx.* 在 vendor 里，构建（import 扩展类）必须在激活窗口内
                self._md = markdown.Markdown(
                    extensions=list(exts_key), output_format="html"
                )
            self._exts_key = exts_key
        self._md.reset()
        return self._md.convert(text)
