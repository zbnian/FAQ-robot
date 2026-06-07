"""
LRU 去重：替代无限增长的 dict（如 feishu_ws._processed_messages /
wecom_ws._processed）。带锁，可跨线程安全使用。

容量上限：默认 10000 条。超过时按 LRU 淘汰最久未访问的 key。
"""
import threading
from collections import OrderedDict
from typing import Any


class _LRUDedup:
    def __init__(self, capacity: int = 10000):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self._data: "OrderedDict[Any, None]" = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()

    def seen(self, key: Any) -> bool:
        """如果 key 已见过返回 True（同时刷新 LRU 顺序），否则标记后返回 False。"""
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return True
            self._data[key] = None
            if len(self._data) > self._capacity:
                self._data.popitem(last=False)
            return False

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
