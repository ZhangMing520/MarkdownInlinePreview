import importlib
import logging

from .engine import Engine

logger = logging.getLogger("MarkdownInlinePreview")

# python-markdown 是默认引擎（由 PC 依赖频道提供）。库未安装时不注册，
# 包依然正常加载；get_engine 会返回 (None, 提示) 优雅降级，而不是让整个包崩溃。
try:
    from .py_md import PythonMarkdownEngine
except ImportError:
    PythonMarkdownEngine = None
    logger.warning("MarkdownInlinePreview: python-markdown 导入失败，默认引擎不可用")

_REGISTRY = {}
if PythonMarkdownEngine is not None:
    _REGISTRY[PythonMarkdownEngine.name] = PythonMarkdownEngine

# markdown-it-py 为 vendor 进包的 v0.2 可选引擎。导入不放在包加载期：zip 安装形态下
# import 会触发 vendor 解压（百个文件、~1 MB），不该发生在 plugin_loaded 的 UI 线程上
# ——首次 get_engine/available_engines 用到时才导入。_LAZY 按消耗式处理：注册成功或
# 导入失败都摘掉名字，失败只告警一次（get_engine 每次防抖渲染都会走到，per-call 会刷屏）。
_LAZY = {"markdown-it-py": (".mdit", "MarkdownItEngine")}

# 懒加载/构造阶段视为"引擎在当前宿主不可用"的异常：
# - ImportError：库文件缺失（非 zip 形态下 vendor 被删等）
# - SyntaxError：vendored mdit 4.x 要求 Python 3.10+，3.8 宿主解析期语法不兼容
# - TypeError：3.8 宿主下 collections.abc 的 ABC 运行时下标
#   （"ABCMeta object is not subscriptable"，3.8 真机实测，非 SyntaxError）
# 仅限模块导入与引擎构造阶段；渲染期 TypeError 不在这里，会照常抛给上层。
_ENGINE_LOAD_ERRORS = (ImportError, SyntaxError, TypeError)

# 已知名字但加载失败的引擎（区别于拼错名字的"未知引擎"，消息要准确）
_BROKEN = set()

# 引擎实例按名字缓存：mdit 每次装配 parser+插件开销大，防抖渲染不该逐次重建
_INSTANCES = {}


def _ensure_registered(name):
    cls = _REGISTRY.get(name)
    if cls is not None:
        return cls
    spec = _LAZY.pop(name, None)
    if spec is None:
        return None
    mod_name, attr = spec
    try:
        module = importlib.import_module(mod_name, __package__)
    except _ENGINE_LOAD_ERRORS as exc:
        _BROKEN.add(name)
        logger.warning(
            "MarkdownInlinePreview: 引擎 %s 在当前宿主不可用（%s: %s），不注册",
            name, type(exc).__name__, exc,
        )
        return None
    cls = getattr(module, attr)
    _REGISTRY[name] = cls
    return cls


def register(name: str, cls) -> None:
    """注册一个新引擎（新增引擎 = 加一个文件 + 注册一行，核心不动）。"""
    _REGISTRY[name] = cls
    _INSTANCES.pop(name, None)


def _degrade(name, reason):
    """引擎在当前宿主不可用（import 或构造阶段失败）时的统一回落。

    有 python-markdown 则降级返回其实例、并按 name 缓存（消息/告警只产生一次，
    后续 get_engine 命中 _INSTANCES 直接复用）；无兜底时返回 (None, 准确说明)，
    与拼错名字的"未知引擎"区分。import 阶段的告警已由 _ensure_registered 记一次，
    此处不再重复。
    """
    if name != "python-markdown":
        pm = _REGISTRY.get("python-markdown")
        if pm is not None:
            try:
                inst = pm()
            except _ENGINE_LOAD_ERRORS as exc:
                logger.error("MarkdownInlinePreview: 降级引擎 python-markdown 构造失败: %s", exc)
                return None, str(exc)
            _INSTANCES[name] = inst
            return inst, "引擎 %s 不可用（%s），已降级到 python-markdown" % (name, reason)
    return None, "引擎 %s 在当前 Sublime 宿主不可用（%s），请改用可用引擎" % (name, reason)


def get_engine(name: str):
    """返回 (engine 实例, 状态消息)。实例按名缓存复用，消息只在首次构建产生。

    - 引擎名拼错：返回 (None, "未知引擎: ...")
    - 引擎在当前宿主不可用（库缺失 / Python 版本过低导致 SyntaxError|TypeError，
      无论 import 阶段还是构造阶段）：有 python-markdown 时统一降级返回其实例，
      否则返回 (None, 准确说明)。
    """
    inst = _INSTANCES.get(name)
    if inst is not None:
        return inst, ""
    cls = _ensure_registered(name)
    if cls is None:
        if name in _BROKEN:
            return _degrade(name, "当前宿主 Python 版本过低或库缺失")
        return None, "未知引擎: %s" % name
    try:
        inst = cls()
    except _ENGINE_LOAD_ERRORS as exc:
        _BROKEN.add(name)
        logger.warning("MarkdownInlinePreview: 引擎 %s 构造失败（%s: %s）",
                       name, type(exc).__name__, exc)
        return _degrade(name, str(exc))
    _INSTANCES[name] = inst
    return inst, ""


def available_engines() -> list:
    # 注意：会触发惰性引擎导入，mdit 模块顶层经 vendor_loader.activate() 临时改进程级
    # sys.path。渲染都串行在 async_render 单 worker 线程，本函数若在主线程调用（如引擎
    # 选择 UI）就会与 worker 的导入并发写 sys.path。当前插件无主线程调用者（仅测试）；
    # 将来接入须经 async_render 串行投递或与导入共锁，勿直接在主线程调。
    for name in list(_LAZY):  # _ensure_registered 会消费 _LAZY，快照后再迭代
        _ensure_registered(name)  # 可导入才列出，缺失形态不外显
    return list(_REGISTRY.keys())
