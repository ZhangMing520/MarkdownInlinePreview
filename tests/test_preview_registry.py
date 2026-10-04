"""内嵌预览多开注册表与窗口布局协调的单元测试。

覆盖：window_id → {source_id: manager} 的增删查、首个预览切两栏/末个还原、
close_manager 两条路径（主动关闭 vs 预览标签正在关闭）。全部用假对象，不依赖真实 Sublime。
"""

import importlib

import pytest


@pytest.fixture
def preview_mod(sublime_shim):
    import mip.preview as mod
    importlib.reload(mod)  # 重新绑定 shim 并清空模块级注册表
    yield mod
    mod._MANAGERS.clear()
    mod._ORIG_LAYOUTS.clear()


class _FakeView:
    def __init__(self, vid):
        self._id = vid
        self.closed = False

    def id(self):
        return self._id

    def is_valid(self):
        return not self.closed

    def close(self):
        self.closed = True


class _FakeManager:
    def __init__(self, win, src_id, pv_id):
        self.window = win
        self.source = _FakeView(src_id)
        self.view = _FakeView(pv_id)
        self.erased = 0

    def is_open(self):
        return self.view is not None and self.view.is_valid()

    def is_source(self, view):
        return view is not None and view.id() == self.source.id()

    def is_preview(self, view):
        return view is not None and self.view is not None and view.id() == self.view.id()

    def erase_phantoms(self):
        self.erased += 1


class _FakeWindow:
    def __init__(self, wid=1, orig_layout="ORIG"):
        self._wid = wid
        self._orig_layout = orig_layout
        self.layout_calls = []
        self.group_focus = []

    def id(self):
        return self._wid

    def get_layout(self):
        return self._orig_layout

    def set_layout(self, layout):
        self.layout_calls.append(layout)

    def active_group(self):
        return 0

    def focus_group(self, group):
        self.group_focus.append(group)


def test_registry_isolates_multiple_managers_per_window(preview_mod):
    win = _FakeWindow(wid=1)
    m1 = _FakeManager(win, 101, 201)
    m2 = _FakeManager(win, 102, 202)
    preview_mod.add_manager(1, 101, m1)
    preview_mod.add_manager(1, 102, m2)

    assert set(preview_mod.get_managers(1)) == {m1, m2}
    assert preview_mod.manager_for_view(1, _FakeView(101)) is m1   # 按源视图
    assert preview_mod.manager_for_view(1, _FakeView(202)) is m2   # 按预览视图
    assert preview_mod.manager_for_view(1, _FakeView(999)) is None
    assert preview_mod.get_managers(2) == []                        # 别的窗口隔离


def test_ensure_split_layout_only_for_first_preview(preview_mod):
    win = _FakeWindow()
    preview_mod.ensure_split_layout(win)
    preview_mod.ensure_split_layout(win)

    assert win.layout_calls == [preview_mod._SPLIT_LAYOUT]  # 只切一次
    assert win.group_focus == []


def test_layout_restored_only_after_last_manager_closed(preview_mod):
    win = _FakeWindow()
    m1 = _FakeManager(win, 101, 201)
    m2 = _FakeManager(win, 102, 202)
    preview_mod.add_manager(1, 101, m1)
    preview_mod.add_manager(1, 102, m2)
    preview_mod.ensure_split_layout(win)

    preview_mod.close_manager(m1)
    assert win.layout_calls == [preview_mod._SPLIT_LAYOUT]  # 还有 m2，不还原
    assert m1.view is None and m1.source  # 视图句柄清空，源视图引用不影响
    assert preview_mod.get_managers(1) == [m2]

    preview_mod.close_manager(m2)
    assert win.layout_calls[-1] == "ORIG"                   # 末个关闭 → 还原
    assert win.group_focus == [0]


def test_close_manager_with_already_closing_view(preview_mod):
    win = _FakeWindow()
    m1 = _FakeManager(win, 101, 201)
    preview_mod.add_manager(1, 101, m1)
    preview_mod.ensure_split_layout(win)

    # 预览标签被手动 × 关闭：视图已在关闭流程，禁止再 close/擦 phantom
    pv = m1.view
    preview_mod.close_manager(m1, close_view=False)

    assert pv.closed is False                               # 没有二次 close
    assert m1.erased == 0
    assert win.layout_calls[-1] == "ORIG"                    # 末个仍还原布局
    assert preview_mod.get_managers(1) == []


def test_close_manager_active_path_erases_and_closes_view(preview_mod):
    win = _FakeWindow()
    m1 = _FakeManager(win, 101, 201)
    preview_mod.add_manager(1, 101, m1)
    pv = m1.view

    preview_mod.close_manager(m1)

    assert pv.closed is True
    assert m1.erased == 1
