from abc import ABC, abstractmethod


class Engine(ABC):
    """统一渲染引擎接口：render(text, settings) -> html 字符串。

    所有引擎（python-markdown / markdown-it-py / ...）都实现此接口，
    产出"引擎原生 HTML"，随后交给 normalize.py 归一到规范 HTML，
    再交给 render.py 做 minihtml 适配。
    """

    #: 引擎名，对应 settings["engine"] 的取值
    name = ""

    @abstractmethod
    def render(self, text: str, settings: dict) -> str:
        """把 Markdown 文本渲染为 HTML。"""
        raise NotImplementedError
