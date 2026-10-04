import logging

from conftest import SETTINGS
from mip.engines import get_engine, available_engines
from mip.engines.py_md import PythonMarkdownEngine


def test_default_engine_registered():
    assert "python-markdown" in available_engines()


def test_render_heading():
    out = PythonMarkdownEngine().render("# Hi", SETTINGS)
    assert "<h1" in out and "Hi" in out


def test_render_table():
    md = "| a | b |\n|---|---|\n| 1 | 2 |"
    out = PythonMarkdownEngine().render(md, SETTINGS)
    assert "<table" in out


def test_render_codehilite():
    out = PythonMarkdownEngine().render("```python\nprint(1)\n```", SETTINGS)
    assert "codehilite" in out or "<span" in out


def test_engine_reuse_no_state_leak():
    # 引擎实例在 get_engine 里按名缓存复用：
    # 链接引用定义等文档级状态不得跨 render 泄漏（依赖 render 内的 reset）
    eng = PythonMarkdownEngine()
    eng.render("[ref]: http://leak\n\n[ref]", SETTINGS)
    out = eng.render("[ref]", SETTINGS)
    assert "http://leak" not in out


def test_get_engine_returns_instance():
    eng, msg = get_engine("python-markdown")
    assert eng is not None
    assert msg == ""


def test_lazy_engine_import_failure_warns_once_and_falls_back(monkeypatch, caplog):
    # 防刷屏：get_engine 每次防抖渲染都会走 _ensure_registered，惰性引擎导入失败
    # 必须只告警一次（失败即从 _LAZY 消费掉名字）；宿主可用 python-markdown 时降级到它，
    # 预览不空白（兑现 CHANGELOG/README 的"自动回落"承诺）。
    import mip.engines as engines

    monkeypatch.setattr(engines, "_LAZY", {"boom": (".nope_such_module", "Nope")})
    monkeypatch.setattr(engines, "_BROKEN", set())
    monkeypatch.setattr(engines, "_INSTANCES", {})
    msgs = []
    for _ in range(3):
        eng, msg = engines.get_engine("boom")
        assert isinstance(eng, PythonMarkdownEngine)  # 每次都拿到降级实例
        msgs.append(msg)
    assert msgs[0] and not any(msgs[1:])              # 说明只产生一次，之后命中缓存
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1


def test_lazy_engine_syntaxerror_typeerror_treated_as_incompatible(monkeypatch):
    # vendored mdit 4.x 在旧 Python 宿主：解析期 SyntaxError，
    # 或运行期 TypeError（'ABCMeta' object is not subscriptable）。
    # 两者都必须视为"宿主不兼容"而非炸包，消息不能误导成"未知引擎"，
    # 且有 python-markdown 时降级到它（import 与构造阶段行为一致）。
    import mip.engines as engines

    real_import = engines.importlib.import_module
    cases = [
        ("boom-syntax", SyntaxError("future syntax")),
        ("boom-type", TypeError("'ABCMeta' object is not subscriptable")),
    ]
    for name, err in cases:
        monkeypatch.setattr(engines, "_LAZY", {name: (".fake", "Fake")})
        monkeypatch.setattr(engines, "_BROKEN", set())
        monkeypatch.setattr(engines, "_INSTANCES", {})

        def fake_import(mod_name, package=None, _err=err):
            if mod_name == ".fake":
                raise _err
            return real_import(mod_name, package)

        monkeypatch.setattr(engines.importlib, "import_module", fake_import)
        eng, msg = engines.get_engine(name)
        assert isinstance(eng, PythonMarkdownEngine)
        assert "未知引擎" not in msg
        assert name in engines._BROKEN


def test_engine_ctor_typeerror_falls_back_to_python_markdown(monkeypatch):
    # 模块导入成功但构造引擎时抛 TypeError（库内部不兼容）：
    # 有 python-markdown 兜底时自动降级，而不是把异常抛给渲染管线
    import mip.engines as engines

    class BadEngine:
        name = "boom-ctor"

        def __init__(self):
            raise TypeError("incompatible runtime generic")

    monkeypatch.setitem(engines._REGISTRY, "boom-ctor", BadEngine)
    monkeypatch.setattr(engines, "_INSTANCES", {})
    monkeypatch.setattr(engines, "_BROKEN", set())
    eng, msg = engines.get_engine("boom-ctor")
    assert isinstance(eng, PythonMarkdownEngine)
    assert "降级" in msg


def test_fence_lang_alias_highlight():
    # jsonc 不是 pygments 词法名，须归一到 json 才有高亮（plan.md 踩过的坑）
    import re
    span_re = r'<span class="(?:nt|s2|mi|p|k|c1)">'
    out = PythonMarkdownEngine().render('```jsonc\n{"name": "mip", "n": 1}\n```\n', SETTINGS)
    assert "codehilite" in out
    assert re.search(span_re, out), out  # JSON 词法 span
    # 未知语言保持素色（无词法 span；语言名本身不进输出）
    out2 = PythonMarkdownEngine().render("```notalang\nplain\n```\n", SETTINGS)
    assert re.search(span_re, out2) is None


def test_fence_lang_alias_preserves_content():
    # 别名归一只能改围栏开行的语言名；外层围栏里展示的 ```jsonc 字样是内容，不能被改
    md = "````markdown\n```jsonc\n{\"a\": 1}\n```\n````\n"
    out = PythonMarkdownEngine().render(md, {})
    assert "```jsonc" in out


def test_fence_lang_alias_tracks_no_lang_fences():
    # 无语言的外层围栏也必须被跟踪：否则里面的 ```jsonc 展示行会被误当开行改写。
    # 直接在 preprocessor 层验契约（改写只应发生在真正的开行），
    # 因为 5 段围栏对 python-markdown 本就是畸形输入，整篇 HTML 结构不可靠。
    from markdown import Markdown
    from mip.engines.py_md import _FenceLangAliasPreprocessor

    run = _FenceLangAliasPreprocessor(Markdown()).run
    # 无语言围栏内的 ```jsonc 是内容：原样保留
    assert run(["```", "```jsonc", "x", "```"]) == ["```", "```jsonc", "x", "```"]
    # 真开行才改写：```jsonc → ``` json（且不留行尾空格）
    assert run(["```jsonc", "x", "```"]) == ["``` json", "x", "```"]
    # 开行带 info 后缀：别名替换后其余保留
    assert run(["```jsonc title=a", "x", "```"]) == ["``` json title=a", "x", "```"]
