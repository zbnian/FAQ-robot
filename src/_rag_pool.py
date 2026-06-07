"""
RAG worker pool（设备硬约束：Ollama 3b 单推理 180s，并发无意义且更慢）

进程内单例：所有通道（飞书 / 企微 / scheduler）共享同一份 max_workers=1
的 ThreadPoolExecutor，等于把 RAG 串行化。
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from src.logger import logger

_rag_executor: Optional[ThreadPoolExecutor] = None


def get_rag_executor() -> ThreadPoolExecutor:
    """获取 RAG executor 单例（max_workers=1，限流）"""
    global _rag_executor
    if _rag_executor is None:
        _rag_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag")
        logger.info("RAG worker pool 已创建（max_workers=1）")
    return _rag_executor


def shutdown_rag_executor(wait: bool = False) -> None:
    """进程退出时关闭 RAG executor（在 main.py KeyboardInterrupt 路径调用）"""
    global _rag_executor
    if _rag_executor is not None:
        _rag_executor.shutdown(wait=wait, cancel_futures=True)
        _rag_executor = None
        logger.info("RAG worker pool 已关闭")
