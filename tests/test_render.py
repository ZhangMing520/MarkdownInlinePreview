import base64
import os
import tempfile

from conftest import SETTINGS
from mip.engines.py_md import PythonMarkdownEngine
from mip.render import (
    convert_inputs,
    convert_strikethrough,
    convert_tables,
    front_matter_to_table,
    inline_local_images,
    render_html,
    split_blocks,
)

# 1x1 透明 PNG
PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"


def test_convert_tables():
    out = convert_tables("<table><tr><td>1</td><td>2</td></tr></table>")
    assert "<table" not in out
    assert "display:inline-block" in out
    assert "1" in out and "2" in out


def test_convert_inputs():
    assert "[x]" in convert_inputs('<input type="checkbox" checked>')
    assert "[ ]" in convert_inputs('<input type="checkbox">')


def test_convert_strikethrough():
    out = convert_strikethrough("<del>old</del>")
    assert "line-through" in out and "old" in out and "<del" not in out


def test_inline_local_images():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "x.png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(PNG_B64))
        out = inline_local_images('<img src="%s">' % path, base_dir=d)
        assert "data:image/png;base64," in out


def test_inline_remote_left_alone():
    html = '<img src="https://example.com/a.png">'
    assert inline_local_images(html) == html


def test_front_matter_to_table():
    md = "---\ntitle: Hi\nfoo: bar\n---\n# Body\n"
    text, table = front_matter_to_table(md)
    assert table is not None
    assert "Hi" in table and "bar" in table
    assert "display:inline-block" not in table  # 仍是 <table>，未转
    # 端到端：front matter 经转换层变 div 网格
    out = render_html(md, SETTINGS, PythonMarkdownEngine())
    assert "display:inline-block" in out
    assert "Hi" in out


def test_split_blocks():
    blocks = split_blocks("<p>a</p><p>b</p>")
    assert len(blocks) == 2


def test_render_html_end_to_end():
    md = "# T\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    out = render_html(md, SETTINGS, PythonMarkdownEngine())
    assert "display:inline-block" in out   # table → div 网格
    # 样式不再由 render_html 嵌入，而由 preview.py 逐块前置 DEFAULT_STYLE
    assert "<style>" not in out
    # 任务列表(- [ ]) / 删除线(~~x~~) 默认扩展不产出 <input>/<del>，需 v0.2 的 GFM 扩展；
    # 转换逻辑由 test_convert_inputs / test_convert_strikethrough 单独覆盖。


def test_split_blocks_preserves_entities():
    # convert_charrefs=True 会把实体解码，重序列化必须重新 escape，
    # 否则代码块里的 &lt;b&gt; 会被还原成真标签
    blocks = split_blocks("<p>hi &amp; bye</p><p><code>&lt;b&gt;x&lt;/b&gt;</code></p>")
    assert blocks[0] == "<p>hi &amp; bye</p>"
    assert "&lt;b&gt;" in blocks[1]
    assert "<b>" not in blocks[1]


def test_split_blocks_void_tags():
    # 非自闭合写法的 void 标签（<hr>/<img>）不能当作开标签压栈，否则吞掉后续所有块
    blocks = split_blocks("<hr><p>a</p><p><img src='x.png'>b</p><p>c</p>")
    assert blocks[0].startswith("<hr")
    assert blocks[1] == "<p>a</p>"
    assert "b" in blocks[2] and "<img" in blocks[2]
    assert blocks[-1] == "<p>c</p>"


def test_inline_local_images_svg_mime():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "x.svg")
        with open(path, "wb") as f:
            f.write(b"<svg/>")
        out = inline_local_images('<img src="%s">' % path, base_dir=d)
        assert "data:image/svg+xml;base64," in out


def test_front_matter_eof_without_newline():
    md = "---\ntitle: Hi\n---"  # 文件末尾无换行
    text, table = front_matter_to_table(md)
    assert table is not None and "Hi" in table
    assert text == ""
