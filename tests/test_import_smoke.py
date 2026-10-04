"""导入冒烟测试：用 sublime shim 替换标准库里的 sublime/sublime_plugin，
验证 ST 依赖模块能正常 import（捕获语法/引用错误）。行为需在真实 Sublime 验证。
"""


def test_import_st_modules(monkeypatch):
    from tests.mocks import sublime_mock
    monkeypatch.setitem(__import__("sys").modules, "sublime", sublime_mock.sublime)
    monkeypatch.setitem(__import__("sys").modules, "sublime_plugin", sublime_mock.sublime_plugin)

    import importlib
    import mip.preview as preview_mod
    import mip.listener as listener_mod
    import mip.settings as settings_mod
    import MarkdownInlinePreview as root_mod

    importlib.reload(preview_mod)
    importlib.reload(listener_mod)
    importlib.reload(settings_mod)
    importlib.reload(root_mod)

    assert preview_mod is not None
    assert listener_mod is not None
    assert settings_mod is not None
    assert root_mod is not None
    # 关键符号应存在
    assert hasattr(preview_mod, "MipTogglePreviewCommand")
    assert hasattr(preview_mod, "PreviewManager")
    assert hasattr(listener_mod, "MipSourceListener")
    assert hasattr(settings_mod, "get_settings")
