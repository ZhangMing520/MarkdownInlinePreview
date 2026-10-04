"""async_render 后台渲染调度的单元测试。

用真实 daemon 工作线程 + Queue，但把 sublime.set_timeout 替换为同步执行，
保证回调时序确定；通过"前置阻塞任务"让 worker 停在指定位置，确定性地覆盖
coalesce（同 owner 排队任务只留最新）语义。
"""

import importlib
import threading

import pytest


@pytest.fixture
def ar(sublime_shim, monkeypatch):
    # 回调在测试里同步执行（真实 Sublime 中由 set_timeout 切回主线程）
    monkeypatch.setattr(sublime_shim.sublime, "set_timeout", lambda fn, delay=0: fn())
    import mip.async_render as mod
    importlib.reload(mod)  # 复位线程/队列/shutdown 标志并绑定 shim
    yield mod
    mod.reset_for_tests()


def _records():
    ok, err = [], []
    return ok, err, ok.append, err.append


def test_success_delivers_result_via_set_timeout(ar):
    ok, err, on_ok, on_err = _records()
    ar.submit(object(), lambda: "html", on_ok, on_err)
    ar.join_for_tests()

    assert ok == ["html"]
    assert err == []


def test_failure_delivers_exception(ar):
    ok, err, on_ok, on_err = _records()
    boom = RuntimeError("render boom")

    def job():
        raise boom

    ar.submit(object(), job, on_ok, on_err)
    ar.join_for_tests()

    assert ok == []
    assert err == [boom]


def test_coalesce_keeps_only_newest_queued_job_per_owner(ar):
    """worker 正忙时同 owner 连投两任务：旧任务在排队阶段被覆盖，绝不执行。"""

    gate = threading.Event()
    pump_started = threading.Event()
    owner = object()
    ran, ok, err = [], [], []

    def pump():
        pump_started.set()
        gate.wait(5.0)  # 卡住唯一工作线程，让后续任务确定地停在排队阶段

    # 先占住 worker
    ar.submit(object(), pump, lambda r: None, lambda e: None)
    assert pump_started.wait(5.0)

    # worker 忙期间同 owner 连投：A 必须被 B 覆盖（B 入队时替换 pending 槽位）
    ar.submit(owner, lambda: ran.append("A") or "A", ok.append, err.append)
    ar.submit(owner, lambda: ran.append("B") or "B", ok.append, err.append)

    gate.set()
    ar.join_for_tests()

    assert ran == ["B"]      # 旧任务体从未执行
    assert ok == ["B"]       # 只有最新任务的成功回调
    assert err == []


def test_jobs_of_different_owners_both_run(ar):
    ok, err, on_ok, on_err = _records()
    ar.submit(object(), lambda: "x", on_ok, on_err)
    ar.submit(object(), lambda: "y", on_ok, on_err)
    ar.join_for_tests()

    assert sorted(ok) == ["x", "y"]


def test_shutdown_rejects_new_jobs_and_stops_worker(ar):
    ran = []
    ar.submit(object(), lambda: ran.append(1), lambda r: None, lambda e: None)
    ar.join_for_tests()

    ar.shutdown()
    ar.join_for_tests()  # 等毒丸被取走、线程退出
    ar.submit(object(), lambda: ran.append(2), lambda r: None, lambda e: None)

    assert ran == [1]  # shutdown 后投递被静默拒绝
    assert not ar._thread.is_alive()
