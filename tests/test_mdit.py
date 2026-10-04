"""markdown-it-py 引擎测试（vendor 在当前 Python 宿主可加载时才跑）。

证明 v0.2 的 GFM 闭环：markdown-it-py 真能产出 <table>/<input>/<del>，
交给 render.py 转换层后变成 minihtml 可显示的 div 网格 / [x] / U+0336 删除线。

vendored 4.x 要求 Python 3.10+；旧宿主（如 ST 的 3.8）下导入会抛 SyntaxError
或 TypeError（ABC 运行时下标），这些测试在该宿主整体 skip——降级路径本身由
test_engines.py 单独钉死。
"""

import sys

try:
    import pytest
except ImportError:
    pytest = None

try:
    from mip.engines.mdit import MarkdownItEngine
except (ImportError, SyntaxError, TypeError):
    MarkdownItEngine = None

pytestmark = pytest.mark.skipif(
    MarkdownItEngine is None or sys.version_info < (3, 10),
    reason="vendored markdown-it-py 4.x 需要 Python 3.10+",
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
    assert "x\u0336" in out               # 删除线 → U+0336 逐字叠加
