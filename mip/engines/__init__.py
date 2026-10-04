import logging

from .engine import Engine

logger = logging.getLogger("MarkdownInlinePreview")

# python-markdown 是默认引擎（由 PC 依赖频道提供）。库未安装时静默不注册，
# 包依然正常加载；get_engine 会返回 (None, 提示) 优雅降级，而不是让整个包崩溃。
try:
    from .py_md import PythonMarkdownEngine
except ImportError:
    PythonMarkdownEngine = None

_REGISTRY = {}
if PythonMarkdownEngine is not None:
    _REGISTRY[PythonMarkdownEngine.name] = PythonMarkdownEngine

# markdown-it-py 为 vendor 进包的 v0.2 可选引擎；vendor 缺失时静默不注册
try:
    from .mdit import MarkdownItEngine
    _REGISTRY[MarkdownItEngine.name] = MarkdownItEngine
except ImportError:
    pass

# 引擎实例按名字缓存：mdit 每次装配 parser+插件开销大，防抖渲染不该逐次重建
_INSTANCES = {}


def register(name: str, cls) -> None:
    """注册一个新引擎（新增引擎 = 加一个文件 + 注册一行，核心不动）。"""
    _REGISTRY[name] = cls
    _INSTANCES.pop(name, None)


def get_engine(name: str):
    """返回 (engine 实例, 状态消息)。实例缓存复用，消息只在构建时产生一次。

    - 引擎不存在：返回 (None, 错误提示)
    - 引擎库缺失（ImportError）：降级到 python-markdown，并记一次日志
    """
    cls = _REGISTRY.get(name)
    if cls is None:
        return None, "未知引擎: %s" % name
    if name in _INSTANCES:
        return _INSTANCES[name], ""
    try:
        inst = cls()
        msg = ""
    except ImportError as exc:
        if name == "python-markdown" or "python-markdown" not in _REGISTRY:
            logger.error("MarkdownInlinePreview: 引擎 %s 初始化失败: %s", name, exc)
            return None, str(exc)
        msg = "引擎 %s 不可用（%s），已降级到 python-markdown" % (name, exc)
        logger.warning("MarkdownInlinePreview: %s", msg)
        inst = _REGISTRY["python-markdown"]()
    _INSTANCES[name] = inst
    return inst, msg


def available_engines() -> list:
    return list(_REGISTRY.keys())
