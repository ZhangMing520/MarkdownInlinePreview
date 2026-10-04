"""Sublime API shim：用于在无 Sublime 环境对 ST 依赖模块做导入冒烟测试。

用 MagicMock 兜底任意属性/调用，只验证模块能 import、无语法/引用错误；
行为正确性仍需在真实 Sublime 内验证。用法见 tests/test_import_smoke.py。
"""

from unittest import mock

sublime = mock.MagicMock()
sublime_plugin = mock.MagicMock()

# 命令基类（TextCommand/WindowCommand/EventListener/ApplicationCommand）属于
# sublime_plugin，绝不应从 sublime 导入。MagicMock 会静默放行 `sublime.TextCommand`，
# 导致真实 ST 下才暴露的 AttributeError 被测试掩盖。显式置空，任何误用都会在导入
# 冒烟测试里失败（class X(None) 触发 TypeError）。
for _name in ("TextCommand", "WindowCommand", "EventListener", "ApplicationCommand"):
    setattr(sublime, _name, None)
