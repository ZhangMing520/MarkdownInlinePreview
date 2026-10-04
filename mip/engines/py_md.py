import markdown

from .engine import Engine


class PythonMarkdownEngine(Engine):
    """默认引擎：python-markdown（PC 依赖频道现成有）。

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
            self._md = markdown.Markdown(extensions=list(exts_key), output_format="html")
            self._exts_key = exts_key
        self._md.reset()
        return self._md.convert(text)
