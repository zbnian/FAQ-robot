"""
FeishuIOWorker - 单线程串行化所有 lark.Client 调用

背景：lark.Client 内部用 asyncio.Lock 绑专属 loop，跨线程直接调行为未定义。
FeishuWebSocket 回调线程 + RAG worker + scheduler 都可能需要调 lark.Client
（reply_text / send_message / send_card），统一走这个单线程 worker 串行化。

队列上限 1000：超过 log warning 并丢弃（不是返回 False 让上游重试，
避免重试风暴）。实际使用中队列很少满。
"""
import queue
import threading
from typing import Callable, Optional

from src.logger import logger


class FeishuIOWorker:
    """单线程 worker 串行化所有 lark.Client 调用"""

    def __init__(self, maxsize: int = 1000):
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._dropped = 0
        self._dropped_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="feishu-io")
        self._thread.start()
        logger.info("FeishuIO worker 已启动")

    def submit(self, fn: Callable, *args, **kwargs) -> bool:
        """提交 lark.Client 调用到单线程队列。队列满则丢并 log。"""
        try:
            self._queue.put_nowait((fn, args, kwargs))
            return True
        except queue.Full:
            with self._dropped_lock:
                self._dropped += 1
            logger.warning(
                "FeishuIO 队列满，丢弃第 %d 个调用（fn=%s）",
                self._dropped, getattr(fn, "__name__", repr(fn)),
            )
            return False

    def _loop(self) -> None:
        while True:
            fn, args, kwargs = self._queue.get()
            try:
                fn(*args, **kwargs)
            except Exception as e:
                logger.exception("FeishuIO 执行失败 (fn=%s): %s", getattr(fn, "__name__", fn), e)
            finally:
                self._queue.task_done()


_feishu_io_instance: Optional[FeishuIOWorker] = None
_feishu_io_lock = threading.Lock()


def get_feishu_io() -> FeishuIOWorker:
    """获取 FeishuIOWorker 进程内单例（双重检查锁）"""
    global _feishu_io_instance
    if _feishu_io_instance is None:
        with _feishu_io_lock:
            if _feishu_io_instance is None:
                _feishu_io_instance = FeishuIOWorker()
                _feishu_io_instance.start()
    return _feishu_io_instance
