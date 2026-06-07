"""
RAG worker pool + 全局 in-flight 槽位（设备硬约束：Ollama 3b 单推理 180s）

进程内单例：所有通道（飞书 / 企微 / scheduler）共享同一份 max_workers=1
的 ThreadPoolExecutor，等于把 RAG 串行化。

全局 in-flight 槽位：
  - 飞书和企微共用同一份「正在跑 + 排队中」计数
  - 超过 MAX_IN_FLIGHT 直接拒绝（回复「系统繁忙，请稍后再试...」）
  - 防止无限堆队列 + 用户长时间静默等
  - 默认 11 = 1 跑 + 10 排：第 12 条入站消息被拒
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from src.logger import logger

MAX_IN_FLIGHT = 11  # 1 跑 + 10 排；第 12 条入站消息被拒

_rag_executor: Optional[ThreadPoolExecutor] = None
_init_lock = threading.Lock()
_in_flight_count = 0
_in_flight_lock = threading.Lock()


def get_rag_executor() -> ThreadPoolExecutor:
    """获取 RAG executor 单例（max_workers=1，限流）"""
    global _rag_executor
    if _rag_executor is None:
        with _init_lock:
            if _rag_executor is None:
                _rag_executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="rag"
                )
                logger.info(
                    f"RAG worker pool 已创建（max_workers=1, max_in_flight={MAX_IN_FLIGHT}）"
                )
    return _rag_executor


def try_acquire_rag_slot() -> bool:
    """非阻塞获取 RAG 槽位。False 表示已满，应直接拒绝。"""
    global _in_flight_count
    with _in_flight_lock:
        if _in_flight_count >= MAX_IN_FLIGHT:
            return False
        _in_flight_count += 1
        return True


def release_rag_slot() -> None:
    """RAG 跑完（包括异常）后释放槽位。"""
    global _in_flight_count
    with _in_flight_lock:
        if _in_flight_count > 0:
            _in_flight_count -= 1


def get_in_flight_count() -> int:
    """当前 in-flight 数（运行中 + 排队中），用于日志/监控。"""
    with _in_flight_lock:
        return _in_flight_count


def shutdown_rag_executor(wait: bool = False) -> None:
    """进程退出时关闭 RAG executor（在 main.py KeyboardInterrupt 路径调用）"""
    global _rag_executor
    if _rag_executor is not None:
        _rag_executor.shutdown(wait=wait, cancel_futures=True)
        _rag_executor = None
        logger.info("RAG worker pool 已关闭")
