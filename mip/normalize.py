def normalize_html(html: str) -> str:
    """引擎输出 → 规范 HTML。

    各引擎产出的 HTML 结构不同（类名 / 属性 / 嵌套方式），在这里归一到一套
    "规范 HTML"，使 render.py 的转换层只针对规范 HTML 写一次，不必为每个引擎
    重写 table→div / input→`[x]` 等逻辑。

    v0.1 只有 python-markdown，其输出已接近规范，此处先透传。
    后续新增引擎（markdown-it-py 等）时，在此加对应的归一适配即可。
    """
    return html
