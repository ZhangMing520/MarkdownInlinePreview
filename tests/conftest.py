import os
import sys

# 让 tests/ 下能直接 import 仓库根的 mip 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 与 mip/settings.py 的 _DEFAULT_EXTENSIONS 一致；
# settings 模块依赖 sublime，测试不可直接 import，故在此单点定义、多文件共享
EXTENSIONS = [
    "tables", "fenced_code", "sane_lists", "attr_list", "md_in_html", "codehilite"
]
SETTINGS = {"extensions": EXTENSIONS}
