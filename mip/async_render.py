"""async_render.py — 渲染管线的后台单线程调度。

为什么需要：整篇 Markdown → HTML 在主线程跑（引擎转换几十至上百毫秒 + 本地图片
base64 文件 IO），打字时每次防抖渲染都卡 UI。纯渲染部分不碰 sublime API，移到
后台线程；只有取源文本（view.substr）与应用结果（phantom 增删等 ST API）留主线程。

为什么只用一个工作线程而不是线程池：
- 引擎实例是进程级缓存单例（engines._INSTANCES），python-markdown 的 Markdown 对象
  convert 期间挂实例状态，并发使用不安全；mdit 的可重入性也不应假设；
- vendor_loader.activate() 临时改进程级 sys.path，并发 with 窗口有竞争；
- 目标只是"不阻塞 UI"，防抖已把频率压到约每 300ms 一次，串行完全够。

过期结果防护（两层）：
- 队列内 coalesce：同一 owner（预览管理器）排队中的旧任务被新任务直接覆盖丢弃；
- 代际校验：正在执行的任务无法取消，回调回到主线程后由 owner 自行比对代际/
  视图有效性（见 preview.py / browser.py 的 render）。
"""

import logging
import queue
import threading

import sublime

logger = logging.getLogger("MarkdownInlinePreview")


class _Job:
    __slots__ = ("func", "on_success", "on_error")

    def __init__(self, func, on_success, on_error):
        self.func = func
        self.on_success = on_success
        self.on_error = on_error


_lock = threading.Lock()
# owner（预览管理器）→ 最新排队任务。直接持对象做键（不能只存 id()：无引用的临时
# 对象可能被 GC 后由下个对象复用 id）；任务在执行前由队列/pending 保活，执行后即释放。
_pending = {}
_queue = None
_thread = None
_shutdown = False


def submit(owner, func, on_success, on_error):
    """投递一个后台渲染任务。

    owner   : 预览管理器实例，作 coalesce 分组键（排队期间被本模块临时持有，执行后释放）
    func    : 后台线程执行的无参可调用，返回值交给 on_success
    on_success / on_error : 主线程执行的回调（sublime.set_timeout），签名分别为
              (result,) / (exception,)

    过期结果由 owner 用自管代际在回调里识别丢弃（渲染期间又投递了新版本时），
    调度层只保证"同 owner 排队中只留最新任务"。
    """

    global _queue, _thread
    with _lock:
        if _shutdown:
            return
        _pending[owner] = _Job(func, on_success, on_error)
        if _thread is None:
            _queue = queue.Queue()
            _thread = threading.Thread(target=_worker, name="mip-render", daemon=True)
            _thread.start()
    # put 在锁外：submit 恒在主线程执行，不会与 shutdown 的 q.put(None) 并发重排；
    # 若将来引入非主线程投递，须把这行也纳入 _lock 保护。
    _queue.put(owner)


def shutdown():
    """插件卸载：丢弃排队任务并让工作线程退出（毒丸）。可重入。

    reload 后是全新模块状态；正在执行的那个任务跑完后其回调会因预览视图已失效
    而被 owner 侧校验挡住。线程引用保留到自然退出（daemon，不阻碍进程退出）。"""

    global _shutdown
    with _lock:
        if _shutdown:
            return
        _shutdown = True
        _pending.clear()
        q = _queue
    if q is not None:
        q.put(None)


def reset_for_tests():
    """测试辅助：停旧工作线程（毒丸）并复位全部模块状态。

    一并把 _thread/_queue 归 None，使后续 submit 不依赖 reload 也能重建线程——
    否则旧线程退场后 _thread 仍指向它，新任务会被投进无人消费的旧队列而永久挂起。
    """

    global _shutdown, _thread, _queue
    shutdown()
    with _lock:
        _shutdown = False
        _thread = None
        _queue = None


def join_for_tests():
    """测试辅助：等待已投递任务全部被工作线程取走并执行完。"""

    q = _queue
    if q is not None:
        q.join()


def _worker():
    q = _queue
    while True:
        owner = q.get()
        try:
            if owner is None:
                return
            _drain_one(owner)
        finally:
            q.task_done()


def _drain_one(owner):
    with _lock:
        # coalesce 生效点：排队期间被同 owner 新任务覆盖后，旧队列条目在这里 pop 不到
        job = _pending.pop(owner, None)
    if job is None:
        return
    try:
        result = job.func()
    except Exception as exc:
        logger.debug("MarkdownInlinePreview: 后台渲染任务异常（交由主线程回调记录）",
                     exc_info=True)
        # 只绑回调、不再闭包整个 job：job.func 捕获的整篇源文本随本帧返回即释放
        sublime.set_timeout(lambda e=exc, cb=job.on_error: cb(e), 0)
    else:
        sublime.set_timeout(lambda r=result, cb=job.on_success: cb(r), 0)
