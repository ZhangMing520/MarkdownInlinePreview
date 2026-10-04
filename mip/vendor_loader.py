"""vendor_loader.py — vendored 库的安装形态适配。

包以解包目录（开发软链 / Packages/ 下手动放置）安装时，mip/vendor 是真实目录，
直接加 sys.path 即可；以 .sublime-package zip（Package Control 发布形态）安装时，
zip 内没有文件系统目录，sys.path 方案失效——此时把 mip/vendor/* 解压到
sublime.cache_path() 下的版本化缓存目录再加 sys.path。

纯 Python（sublime 仅在解压路径上懒加载），zip 解压逻辑可在 .venv 直测。
"""

import logging
import os
import shutil
import sys
import zipfile
from contextlib import contextmanager

logger = logging.getLogger("MarkdownInlinePreview")

# zip 内 vendor 前缀与缓存目录名
_ZIP_PREFIX = "mip/vendor/"
_CACHE_BASE = "MarkdownInlinePreview"


@contextmanager
def activate():
    """把 vendor 目录临时加到 sys.path 顶部（with 结束后移除）。

    供引擎在构建 markdown.Markdown(extensions=[...]) 时使用——pymdownx.* 等扩展
    以顶层模块名 import，且 markdown_it 内部也绝对 import mdurl，无法走包相对路径。
    import 完成即移除，避免永久遮蔽其他插件的同名顶层模块；已导入包的子模块
    靠包自己的 __path__ 解析，移除 sys.path 条目不影响后续懒加载。
    """

    path = resolve_vendor_dir(_engines_dir())
    added = path not in sys.path
    if added:
        sys.path.insert(0, path)
    try:
        yield path
    finally:
        if added:
            sys.path.remove(path)


def _engines_dir():
    # mip/vendor_loader.py → mip/engines（zip 安装时是指向 zip 内部的虚拟路径）
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "engines")


def resolve_vendor_dir(engines_dir: str) -> str:
    """返回可加入 sys.path 的 vendor 目录。

    engines_dir: mip/engines 的路径（由调用方传 os.path.dirname(__file__)，
    zip 安装时是指向 zip 内部的虚拟路径）。找不到 zip 时原样返回 vendor 路径，
    让后续 import 抛 ImportError、引擎注册层走既有的优雅降级。
    """

    vendor = os.path.join(os.path.dirname(engines_dir), "vendor")
    if os.path.isdir(vendor):
        return vendor
    zip_path = _find_package_zip(vendor)
    if zip_path is None:
        return vendor
    try:
        import sublime

        cache_root = sublime.cache_path()
    except ImportError:
        # 非 Sublime 环境（单测）不会走到解压分支，保险起见不炸
        return vendor
    return _extract_vendor(zip_path, cache_root)


def resolve_assets_dir() -> str:
    """mip/assets（KaTeX/mermaid 等浏览器端静态资源）的可用目录。

    Python 只在 zip 安装时才需要读这些文件（往浏览器发字节流），解包安装时
    目录天然可用；zip 安装则同 vendor 一样解压到缓存。
    """

    assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
    if os.path.isdir(assets):
        return assets
    zip_path = _find_package_zip(assets)
    if zip_path is None:
        return assets
    try:
        import sublime

        cache_root = sublime.cache_path()
    except ImportError:
        return assets
    return _extract_prefix(zip_path, cache_root, "mip/assets/", "assets")


def _find_package_zip(path):
    """从 vendor 虚拟路径向上找 .sublime-package（zip 本体）。"""

    p = os.path.abspath(path)
    while True:
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
        if p.endswith(".sublime-package"):
            return p


def _extract_vendor(zip_path: str, cache_root: str) -> str:
    # zip 的 mtime+size 作缓存键：包升级（zip 变化）自动换新目录，旧目录清理
    key = "%d-%d" % (int(os.path.getmtime(zip_path)), os.path.getsize(zip_path))
    return _extract_prefix(zip_path, cache_root, _ZIP_PREFIX, "vendor-" + key)


def _extract_prefix(zip_path: str, cache_root: str, prefix: str, dest_name: str) -> str:
    dest = os.path.join(cache_root, _CACHE_BASE, dest_name)
    sentinel = os.path.join(dest, ".ok")
    if not os.path.exists(sentinel):
        logger.info("MarkdownInlinePreview: zip 安装，解压 %s 到 %s", prefix, dest)
        os.makedirs(dest, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if not name.startswith(prefix) or name.endswith("/"):
                    continue
                target = os.path.join(dest, name[len(prefix):])
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as out:
                    out.write(src.read())
        with open(sentinel, "w") as f:
            f.write("ok")
        if dest_name.startswith("vendor-"):
            _clean_old(os.path.dirname(dest), keep=dest_name)
    return dest


def _clean_old(cache_dir: str, keep: str):
    try:
        for name in os.listdir(cache_dir):
            if name.startswith("vendor-") and name != keep:
                shutil.rmtree(os.path.join(cache_dir, name), ignore_errors=True)
    except OSError:
        pass
