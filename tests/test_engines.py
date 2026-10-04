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


def test_lazy_engine_import_failure_warns_once(monkeypatch, caplog):
    # 防刷屏：get_engine 在每次防抖渲染都会走 _ensure_registered，
    # 惰性引擎导入失败必须只告警一次（失败即从 _LAZY 消费掉名字）
    import mip.engines as engines

    monkeypatch.setattr(engines, "_LAZY", {"boom": (".nope_such_module", "Nope")})
    for _ in range(3):
        eng, msg = engines.get_engine("boom")
        assert eng is None and msg
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1


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
