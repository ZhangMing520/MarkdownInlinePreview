import os
import sys

# 让 tests/ 下能直接 import 仓库根的 mip 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 测试固定使用此列表（mip/settings.py 依赖 sublime，测试不可直接 import）。
# 它是内容的手动副本，与 settings 的 _DEFAULT_EXTENSIONS 无联动：
# 默认扩展变更不会自动反映到这里，测试只测这份列表的行为
EXTENSIONS = [
    "tables", "fenced_code", "sane_lists", "attr_list", "md_in_html", "codehilite",
    "toc", "pymdownx.tasklist", "pymdownx.tilde",
]
SETTINGS = {"extensions": EXTENSIONS}
