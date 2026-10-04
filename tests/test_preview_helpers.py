"""is_preview_view 的宿主形态兼容性测试。

背景：ST 4205+ 的 Python 3.14 宿主里，ViewEventListener.is_applicable 收到的是
view.settings()（Settings 对象），旧宿主传 View 本身。2026-10-04 在真机 Build 4215
（3.3 宿主禁用）上因把 Settings 当 View 用而崩溃，本文件防回归。
"""

import importlib


def test_preview_view_compresses_placeholder_line_height(sublime_shim):
    # 块间空隙来自空占位行的行盒高度（非 CSS margin）：预览视图必须设负行 padding
    # 压缩空行，phantom 内容行由内容最小高度钳住不受影响。该设置被删则空隙回到 ~19px。
    import mip.preview as preview_mod
    importlib.reload(preview_mod)

    class _Settings:
        def __init__(self):
            self._d = {}

        def set(self, k, v):
            self._d[k] = v

        def get(self, k, default=None):
            return self._d.get(k, default)

    class _View:
        def __init__(self):
            self._s = _Settings()
            self.syntax = None

        def settings(self):
            return self._s

        def set_scratch(self, flag):
            self.scratch = flag

        def set_read_only(self, flag):
            self.read_only = flag

        def set_syntax_file(self, syntax):
            self.syntax = syntax

    mgr = preview_mod.PreviewManager.__new__(preview_mod.PreviewManager)
    v = _View()
    mgr._configure_view(v)
    assert v._s.get("line_padding_top") is not None
    assert v._s.get("line_padding_bottom") is not None
    assert v._s.get("line_padding_top") < 0
    assert v._s.get("line_padding_bottom") < 0


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


def test_cursor_ratio_uses_rowcol_only(sublime_shim):
    # 钉住实现契约：只用 sel/rowcol/size（View 没有 line_count()/rowcount()），
    # 光标位置与视图大小用两个可区分的假位置（0 值会碰撞，不能当哨兵用）。
    import mip.preview as preview_mod
    importlib.reload(preview_mod)

    class _FakeView:
        def __init__(self, cursor_row, last_row):
            self._rows = {10: cursor_row, 200: last_row}

        def sel(self):
            class _R:
                def begin(self):
                    return 10
            return [_R()]

        def rowcol(self, tp):
            return (self._rows[tp], 0)

        def size(self):
            return 200

    view = _FakeView(cursor_row=0, last_row=9)
    assert preview_mod.cursor_ratio(view) == 0.0   # 文档顶
    view = _FakeView(cursor_row=5, last_row=9)
    assert preview_mod.cursor_ratio(view) == 0.5   # 第 6 行 / 共 10 行
    view = _FakeView(cursor_row=9, last_row=9)
    assert preview_mod.cursor_ratio(view) == 0.9   # 文档底（末行无换行）


def test_target_block_maps_ratio_into_valid_range(sublime_shim):
    # 比例 → 块序号：必须始终落在 0..blocks-1（ratio 接近 1 时不能越界）
    import mip.preview as preview_mod
    importlib.reload(preview_mod)

    assert preview_mod.target_block(0.0, 29) == 0
    assert preview_mod.target_block(0.86, 29) == 24
    assert preview_mod.target_block(1.0, 29) == 28   # 末块，而非 29
    assert preview_mod.target_block(0.5, 1) == 0     # 单块文档


def test_proportional_y_linear_mapping_with_guard(sublime_shim):
    # text_to_layout 不可用时的兜底：块序号线性映射到 [0, max_y]
    import mip.preview as preview_mod
    importlib.reload(preview_mod)

    assert preview_mod.proportional_y(0, 29, 4005.0) == 0.0
    assert preview_mod.proportional_y(28, 29, 4005.0) == 4005.0   # 末块到可滚动底
    assert abs(preview_mod.proportional_y(14, 29, 4005.0)
               - 4005.0 * 0.5) < 1e-9
    assert preview_mod.proportional_y(0, 1, 100.0) == 0.0         # 单块文档防除零
