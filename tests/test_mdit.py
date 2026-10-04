"""markdown-it-py 引擎测试（vendor 存在时才跑）。

证明 v0.2 的 GFM 闭环：markdown-it-py 真能产出 <table>/<input>/<del>，
交给 render.py 转换层后变成 minihtml 可显示的 div 网格 / [x] / line-through。
"""

try:
    import pytest
except ImportError:
    pytest = None

try:
    from mip.engines.mdit import MarkdownItEngine
except ImportError:
    MarkdownItEngine = None

pytestmark = pytest.mark.skipif(
    MarkdownItEngine is None, reason="markdown-it-py 未 vendor 进包"
) if pytest is not None else None


def test_engine_registered():
    from mip.engines import available_engines
    assert "markdown-it-py" in available_engines()


def test_gfm_renders_real_tags():
    out = MarkdownItEngine().render("| a | b |\n|---|---|\n| 1 | 2 |\n\n- [ ] todo\n\n~~x~~", {})
    assert "<table" in out          # 表格（python-markdown 默认扩展产不出）
    assert "<input" in out          # 任务列表复选框
    assert "<del" in out or "<s" in out   # 删除线


def test_render_html_converts_gfm():
    from mip.render import render_html
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n\n- [x] done\n\n~~x~~"
    out = render_html(md, {"engine": "markdown-it-py", "extensions": []}, MarkdownItEngine())
    assert "display:inline-block" in out   # table → div 网格
    assert "[x]" in out                    # 任务列表 → [x]
    assert "line-through" in out           # 删除线 → line-through
