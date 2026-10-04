import base64
import os
import re
import tempfile

from conftest import SETTINGS
from mip.engines.py_md import PythonMarkdownEngine
from mip.render import (
    convert_code_blocks,
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
    assert "mip-tgrid" in out
    assert "1" in out and "2" in out
    # nbsp 补齐列宽是跨行对齐的机制
    assert "&nbsp;" in out


def test_convert_tables_header_detected():
    out = convert_tables(
        "<table><thead><tr><th>h1</th><th>h2</th></tr></thead>"
        "<tbody><tr><td>a</td><td>b</td></tr></tbody></table>"
    )
    assert "mip-tgrid" in out
    assert "font-weight:bold" in out  # 表头行


def test_convert_tables_wide_falls_back_to_cards():
    # 单列内容 100 半角 → 总宽超阈值，网格会裁切，必须走卡片布局
    wide = "x" * 100
    out = convert_tables(
        "<table><thead><tr><th>k</th></tr></thead>"
        "<tbody><tr><td>%s</td></tr></tbody></table>" % wide
    )
    assert "mip-tgrid" not in out
    assert "mip-tcards" in out
    assert wide in out


def test_convert_tables_cjk_width():
    # 40 个 CJK 字符 = 80 半角单位，超过 72 的网格阈值
    out = convert_tables(
        "<table><thead><tr><th>列</th></tr></thead>"
        "<tbody><tr><td>%s</td></tr></tbody></table>" % ("汉" * 40)
    )
    assert "mip-tcards" in out


def test_convert_tables_rich_cell_falls_back_to_cards():
    # 含 img 的窄表：nbsp 补齐测不出图片宽度，网格对齐必然失效 → 卡片
    out = convert_tables(
        "<table><tr><td><img src=\"a.png\" alt=\"pic\"></td><td>ok</td></tr></table>"
    )
    assert "mip-tgrid" not in out
    assert "mip-tcards" in out
    assert "<img" in out
    # 块级内容同理
    out = convert_tables(
        "<table><tr><td><div>block</div></td><td>ok</td></tr></table>"
    )
    assert "mip-tgrid" not in out and "mip-tcards" in out


def test_convert_tables_narrow_cjk_grid():
    # 短 CJK 内容（依赖 4 + 方式 4 → 总宽远小于阈值）应留在网格且补齐数按 CJK=2 计
    out = convert_tables(
        "<table><thead><tr><th>依赖</th><th>方式</th></tr></thead>"
        "<tbody><tr><td>a</td><td>b</td></tr></tbody></table>"
    )
    assert "mip-tgrid" in out
    # "依赖" 列宽 4，"a" 需补 4-1+2(gutter)=5 个 nbsp
    assert "a&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;" in out


def test_convert_tables_card_labels():
    out = convert_tables(
        "<table><thead><tr><th>col1</th><th>col2</th></tr></thead>"
        "<tbody><tr><td>%s</td><td>val</td></tr></tbody></table>" % ("x" * 100)
    )
    # 卡片内非首列带表头名前缀
    assert "col2:" in out and "val" in out


def test_convert_inputs():
    assert "[x]" in convert_inputs('<input type="checkbox" checked>')
    assert "[ ]" in convert_inputs('<input type="checkbox">')


def test_convert_code_blocks_modern_passthrough():
    # Build 4170+：原生 <pre> 保留，交给 CSS pre-wrap
    html = "<pre>a\nb</pre>"
    assert convert_code_blocks(html, True) == html


def test_convert_code_blocks_legacy():
    html = "<pre>def f():\n    return 1\n\nx = 2</pre>"
    out = convert_code_blocks(html, False)
    assert "<pre" not in out
    assert 'class="mip-pre"' in out
    assert out.count("<div>") == 4             # 4 个源码行（含 1 空行）各一个 div
    assert "&nbsp;&nbsp;&nbsp;&nbsp;return 1" in out   # 缩进转 nbsp
    assert "<div>&nbsp;</div>" in out          # 空行占位保行高
    # pygments 把空白编码进 <span class="w">  </span>：同样转 nbsp
    out2 = convert_code_blocks(
        '<pre><span class="w">    </span><span class="k">if</span> x:\n</pre>', False
    )
    assert '<span class="w">&nbsp;&nbsp;&nbsp;&nbsp;</span>' in out2
    # tab 按 4 空格展开
    out3 = convert_code_blocks("<pre>\tx</pre>", False)
    assert "&nbsp;&nbsp;&nbsp;&nbsp;x" in out3
    # <pre> 闭标签前的单个换行（markdown-it 输出形态）按 HTML 规范忽略，不产生空行 div
    out4 = convert_code_blocks("<pre>a\n</pre>", False)
    assert out4.count("<div>") == 1 and "<div>&nbsp;</div>" not in out4
    # pygments/mdit 实际形态：换行在 </code> 前
    out5 = convert_code_blocks("<pre><code>a\n</code></pre>", False)
    inner5 = re.findall(r"<div>.*?</div>", out5)
    assert len(inner5) == 1 and "a</code>" in inner5[0]


def test_render_html_code_block_legacy_end_to_end():
    md = "```python\ndef f():\n    return 1\n```"
    out = render_html(md, SETTINGS, PythonMarkdownEngine(), pre_wrap=False)
    assert "<pre" not in out and "mip-pre" in out


def test_convert_strikethrough():
    out = convert_strikethrough("<del>old</del>")
    assert "<del" not in out
    assert out == "o\u0336l\u0336d\u0336"   # 逐字叠加 U+0336
    # 连续空白不叠（避免空格上出现多余划线/异常 shaping）
    assert convert_strikethrough("<del>a b</del>") == "a\u0336 b\u0336"
    # 行内标签保留，只对文本节点叠加
    out = convert_strikethrough("<del>a <code>b</code></del>")
    assert out == "a\u0336 <code>b\u0336</code>"
    # HTML 实体作为一个整体，组合符加在实体之后（作用于解析出的字符）
    assert convert_strikethrough("<del>&amp;x</del>") == "&amp;\u0336x\u0336"
    # <s> 同义标签同样处理
    assert convert_strikethrough("<s>y</s>") == "y\u0336"


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
    # 端到端：front matter 经转换层变网格（窄表）
    out = render_html(md, SETTINGS, PythonMarkdownEngine())
    assert "mip-tgrid" in out
    assert "Hi" in out


def test_split_blocks():
    blocks = split_blocks("<p>a</p><p>b</p>")
    assert len(blocks) == 2


def test_render_html_end_to_end():
    md = "# T\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    out = render_html(md, SETTINGS, PythonMarkdownEngine())
    assert "mip-tgrid" in out   # table → 等宽字体网格（窄表）
    # 样式不再由 render_html 嵌入，而由 preview.py 逐块前置 DEFAULT_STYLE
    assert "<style>" not in out


def test_render_html_default_engine_gfm():
    # vendored pymdownx 子集：默认引擎直接产出 <input>/<del>，转换层转成 minihtml 形态
    md = "- [x] done\n\n~~gone~~"
    out = render_html(md, SETTINGS, PythonMarkdownEngine())
    assert "[x]" in out                       # checkbox → [x]
    assert "g\u0336o\u0336n\u0336e\u0336" in out   # 删除线 → U+0336 逐字叠加
    assert "line-through" not in out         # 旧的无效 span 不再输出
    assert "<input" not in out and "<del" not in out


def test_render_body_no_guess_lang():
    # 无语言标注的围栏块不做 pygments 语言猜测：
    # 猜测会把目录树的制表线字符（├── │）判成 error token，在完整 pygments 样式下染红
    from mip.render import render_body
    md = "```text\ntext\n```\n\n```\n├── a\n│   └── b\n```\n"
    body = render_body(md, SETTINGS, PythonMarkdownEngine(), base_dir=".")
    assert 'class="err"' not in body
    assert "├── a" in body


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
