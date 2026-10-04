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
