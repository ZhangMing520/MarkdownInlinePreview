"""is_preview_view 的宿主形态兼容性测试。

背景：ST 4205+ 的 Python 3.14 宿主里，ViewEventListener.is_applicable 收到的是
view.settings()（Settings 对象），旧宿主传 View 本身。2026-10-04 在真机 Build 4215
（3.3 宿主禁用）上因把 Settings 当 View 用而崩溃，本文件防回归。
"""

import importlib


def test_is_preview_view_accepts_settings_or_view(sublime_shim):
    import mip.preview as preview_mod
    importlib.reload(preview_mod)  # 重新绑定 shim 后的 sublime

    class _Settings:
        def __init__(self, flag):
            self._v = flag

        def get(self, key, default=None):
            return self._v

    class _View:
        def __init__(self, s):
            self._s = s

        def settings(self):
            return self._s

    assert preview_mod.is_preview_view(_View(_Settings(True))) is True    # 旧宿主形态
    assert preview_mod.is_preview_view(_Settings(True)) is True           # 3.14 宿主形态
    assert preview_mod.is_preview_view(_View(_Settings(False))) is False
    assert preview_mod.is_preview_view(_Settings(False)) is False
