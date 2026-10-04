import re

import markdown
from markdown.extensions import Extension
from markdown.preprocessors import Preprocessor

from .. import vendor_loader
from .engine import Engine

# 默认引擎缺的 GFM 能力由 vendored pymdownx 子集补齐（任务列表/删除线）。
# 注意 "pymdownx.tilde" 的 GFM 形态：~~x~~ → <del>（默认 smart 模式关，与 GitHub 一致）
_GFM_EXTS = {"pymdownx.tasklist", "pymdownx.tilde"}

# 用户常用的围栏语言名 → pygments 词法名回退候选。
# codehilite 对不认识的词法名直接放弃高亮（guess_lang 已关），需要归一。
# 候选表在加载时按捆绑 pygments 自动过滤：get_lexer_by_name 解析得到的名字
# （sh/golang/rs/c++ 等，随 pygments 版本而变）不进表——覆盖原生词法属于降级
# （console→bash 丢 $ 提示符词法、asm→nasm 换掉 GAS），只有解析不到的才改写。
_FENCE_ALIAS_FALLBACKS = {
    "jsonc": "json", "json5": "json", "yml": "yaml",
    "sh": "bash", "shell": "bash", "zsh": "bash", "console": "bash",
    "golang": "go", "rs": "rust", "c++": "cpp", "cs": "csharp",
    "docker": "dockerfile", "objc": "objective-c", "asm": "nasm",
}


def _resolve_alias_fallbacks():
    try:
        from pygments.lexers import get_lexer_by_name
    except ImportError:
        # 无 pygments 时无人高亮，改不改写无观感差别，候选表原样生效
        return dict(_FENCE_ALIAS_FALLBACKS)
    resolved = {}
    for lang, fallback in _FENCE_ALIAS_FALLBACKS.items():
        try:
            get_lexer_by_name(lang)
        except ValueError:
            resolved[lang] = fallback
    return resolved


_FENCE_ALIASES = _resolve_alias_fallbacks()

_FENCE_OPEN_RE = re.compile(
    r"^(\s{0,3})(`{3,}|~{3,})[ \t]*([A-Za-z0-9_+#.-]+)?[ \t]*(.*)$"
)

# 闭合围栏正则按 (字符, 长度) 缓存；文档里实际只有少数几种，热点循环里零编译
_CLOSE_RES = {}


class _FenceLangAliasPreprocessor(Preprocessor):
    """把围栏开行的语言别名归一到 pygments 词法名。

    跟踪所有围栏开行（含无语言的，语言在正则里可选；闭合须字符相同且长度不小于
    开行——CommonMark 规则），否则无语言围栏里展示的 ```jsonc 字样会被误当开行
    改写。只改写语言名，围栏内容一律原样保留。
    """

    def run(self, lines):
        out = []
        close_re = None
        for line in lines:
            if close_re is None:
                m = _FENCE_OPEN_RE.match(line)
                if m:
                    lang = m.group(3)
                    alias = _FENCE_ALIASES.get(lang.lower()) if lang else None
                    if alias:
                        line = "%s%s %s" % (m.group(1), m.group(2), alias)
                        if m.group(4):
                            line += " " + m.group(4)
                    key = (m.group(2)[0], len(m.group(2)))
                    close_re = _CLOSE_RES.get(key)
                    if close_re is None:
                        close_re = _CLOSE_RES[key] = re.compile(
                            r"^\s{0,3}%s{%d,}\s*$" % (re.escape(key[0]), key[1])
                        )
            elif close_re.match(line):
                close_re = None
            out.append(line)
        return out


class _FenceLangAliasExtension(Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(_FenceLangAliasPreprocessor(md), "mip_fence_alias", 100)


class PythonMarkdownEngine(Engine):
    """默认引擎：python-markdown（PC 依赖频道现成有）+ vendored pymdownx 子集。

    Markdown 对象按 extensions 复用（构建解析器开销大）；
    convert() 不会自动重置状态（链接引用定义会跨文档泄漏），必须逐次 reset()。
    """

    name = "python-markdown"

    def __init__(self):
        self._md = None
        self._exts_key = None

    def render(self, text: str, settings: dict) -> str:
        exts_key = tuple(settings.get("extensions", []))
        if self._md is None or exts_key != self._exts_key:
            with vendor_loader.activate():
                # pymdownx.* 在 vendor 里，构建（import 扩展类）必须在激活窗口内。
                # guess_lang=False：无语言标注的围栏块按纯文本渲染——pygments 的语言猜测
                # 会把目录树等文本的制表线字符（├── │）判成 error token 染红。
                # _FenceLangAliasExtension 永远启用（jsonc→json 等别名归一，见上）。
                self._md = markdown.Markdown(
                    extensions=list(exts_key) + [_FenceLangAliasExtension()],
                    extension_configs={"codehilite": {"guess_lang": False}},
                    output_format="html",
                )
            self._exts_key = exts_key
        self._md.reset()
        return self._md.convert(text)
