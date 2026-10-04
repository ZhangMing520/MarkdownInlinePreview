"""vendor_loader：zip 安装形态的解压与缓存逻辑直测。"""

import os
import sys
import zipfile

import pytest

from mip.vendor_loader import _extract_vendor, _find_package_zip, resolve_vendor_dir


def _make_package_zip(tmp_path):
    """构造一个形如 .sublime-package 的 zip：mip/vendor/ 下放一个可 import 的标记模块。

    用独一无二的模块名 mipvendor_mark：测试会话里 mdit 引擎可能已把真实
    markdown_it 导入 sys.modules，同名模块会取到缓存实例而无法断言。
    """
    zip_path = str(tmp_path / "MarkdownInlinePreview.sublime-package")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("MarkdownInlinePreview.py", "x = 1\n")
        zf.writestr("mip/__init__.py", "")
        zf.writestr("mip/engines/__init__.py", "")
        zf.writestr("mip/vendor/__init__.py", "")
        zf.writestr("mip/vendor/mipvendor_mark.py", "MARK = 42\n")
        zf.writestr("mip/vendor/mdurl/__init__.py", "")
        # 目录条目与非 vendor 文件应被忽略
        zf.writestr("mip/vendor/", "")
        zf.writestr("README.md", "readme")
    return zip_path


def test_find_package_zip(tmp_path):
    zip_path = _make_package_zip(tmp_path)
    virtual = os.path.join(zip_path, "mip", "engines")
    assert _find_package_zip(virtual) == zip_path
    # 普通目录树向上找不到 zip → None
    assert _find_package_zip(str(tmp_path / "a" / "b")) is None


def test_extract_vendor(tmp_path):
    zip_path = _make_package_zip(tmp_path)
    cache_root = str(tmp_path / "cache")
    dest = _extract_vendor(zip_path, cache_root)

    # 只解压 mip/vendor/*，且保持相对结构
    assert os.path.isfile(os.path.join(dest, "mipvendor_mark.py"))
    assert os.path.isfile(os.path.join(dest, "mdurl", "__init__.py"))
    assert not os.path.exists(os.path.join(dest, "README.md"))
    assert os.path.isfile(os.path.join(dest, ".ok"))  # 完成标记
    # 解压结果可直接 import
    sys.path.insert(0, dest)
    try:
        import importlib

        assert importlib.import_module("mipvendor_mark").MARK == 42
    finally:
        sys.path.remove(dest)
        sys.modules.pop("mipvendor_mark", None)


def test_extract_vendor_cache_hit_and_cleanup(tmp_path):
    zip_path = _make_package_zip(tmp_path)
    cache_root = str(tmp_path / "cache")
    dest1 = _extract_vendor(zip_path, cache_root)
    dest2 = _extract_vendor(zip_path, cache_root)
    assert dest1 == dest2  # 同一个 zip 命中缓存，不重复解压
    # zip 变化（模拟包升级）→ 新缓存目录，旧目录（含残留的假目录）被清理
    old = os.path.join(os.path.dirname(dest1), "vendor-111-222")
    os.makedirs(old)
    os.utime(zip_path, (0, 0))  # 改 mtime → 缓存键变化
    dest3 = _extract_vendor(zip_path, cache_root)
    assert dest3 != dest1
    assert not os.path.exists(old)
    assert not os.path.exists(dest1)


def test_resolve_unpacked_short_circuit(tmp_path):
    # vendor 是真实目录时直接返回，不触碰 zip/sublime
    pkg = tmp_path / "pkg"
    (pkg / "mip" / "vendor").mkdir(parents=True)
    out = resolve_vendor_dir(str(pkg / "mip" / "engines"))
    assert os.path.basename(out) == "vendor"


def test_resolve_no_zip_returns_vendor_path(tmp_path):
    # 虚拟路径找不到 zip：返回原路径（调用方走 ImportError 降级），不抛异常
    pkg = tmp_path / "pkg"
    (pkg / "mip" / "engines").mkdir(parents=True)  # 无 vendor 目录
    out = resolve_vendor_dir(str(pkg / "mip" / "engines"))
    assert out.endswith("vendor")
