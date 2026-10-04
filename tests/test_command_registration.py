"""命令注册防回归：mip 子模块里定义的每个 *Command 必须出现在根模块命名空间。

背景：Sublime 主要扫描被直接加载的插件根模块（MarkdownInlinePreview.py）的 dir()
来注册命令，子模块里定义但未被根模块显式导入的命令类不会被注册，
view.run_command() 对未注册命令静默空转。2026-10-04 占位文本命令
MipSetTextCommand 即因此从未执行：预览缓冲为空，全部 phantom 挂在点 0，
同步滚动永远定位到顶部。本测试钉死这一耦合。
"""

import ast
import importlib
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIP_DIR = os.path.join(REPO_ROOT, "mip")
ROOT_MODULE = os.path.join(REPO_ROOT, "MarkdownInlinePreview.py")


def _command_classes_in(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    return [node.name for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name.endswith("Command")]


def _mip_py_files():
    # 递归全部子包（engines 等将来的命令类也要被钉住）；vendor 是第三方库，
    # 不属于"我们的命令须进根模块"的约定范围
    for dirpath, dirnames, filenames in os.walk(MIP_DIR):
        dirnames[:] = [d for d in dirnames if d not in ("vendor", "__pycache__")]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def test_every_command_class_is_exported_by_root_module(sublime_shim):
    defined = set()
    for path in _mip_py_files():
        defined.update(_command_classes_in(path))

    assert defined, "mip/ 下应至少定义一个命令类（测试本身失效的护栏）"

    root = importlib.import_module("MarkdownInlinePreview")
    importlib.reload(root)

    missing = sorted(name for name in defined if not hasattr(root, name))
    assert not missing, (
        "以下命令类在 mip/ 中定义但未在 MarkdownInlinePreview.py 根模块导入，"
        "Sublime 不会注册它们：%s" % missing)
