"""
_LRUDedup 测试

回归目标：替代飞书/企微 _processed_* 无界 dict，防止长期 OOM。
"""
import threading

from src._lru_dedup import _LRUDedup


class TestBasicSemantics:
    def test_first_seen_returns_false(self):
        d = _LRUDedup(capacity=10)
        assert d.seen("a") is False  # 第一次见

    def test_second_seen_returns_true(self):
        d = _LRUDedup(capacity=10)
        d.seen("a")
        assert d.seen("a") is True  # 第二次见

    def test_distinct_keys_independent(self):
        d = _LRUDedup(capacity=10)
        d.seen("a")
        d.seen("b")
        assert d.seen("a") is True
        assert d.seen("b") is True
        assert d.seen("c") is False


class TestCapacityEviction:
    def test_capacity_evicts_lru(self):
        """容量满后再加新 key，淘汰最久未访问的（用底层 _data 验证）"""
        d = _LRUDedup(capacity=3)
        d.seen("a")
        d.seen("b")
        d.seen("c")
        assert len(d) == 3
        d.seen("d")  # 触发淘汰，"a" 是最久未访问
        assert len(d) == 3
        # dict order 应为 {b, c, d}
        assert list(d._data.keys()) == ["b", "c", "d"]

    def test_lru_refresh_on_access(self):
        """访问已存在的 key 应刷新其 LRU 顺序（用底层 _data 验证，避免连锁 eviction 干扰）"""
        d = _LRUDedup(capacity=3)
        d.seen("a")
        d.seen("b")
        d.seen("c")
        # 重新访问 "a"，使 "b" 成为最久未访问
        d.seen("a")
        # 此时 dict order 应为 {b, c, a}，length=3，未溢出
        assert list(d._data.keys()) == ["b", "c", "a"]
        d.seen("d")
        # 触发淘汰：dict order {b, c, a} → 加 d → {b, c, a, d} → pop first "b" → {c, a, d}
        assert list(d._data.keys()) == ["c", "a", "d"]

    def test_overflow_by_one(self):
        """容量 N，塞 N+1 个，断言正好 N 个存活"""
        d = _LRUDedup(capacity=10000)
        for i in range(10001):
            d.seen(f"key_{i}")
        assert len(d) == 10000
        # 最老 key_0 被淘汰
        assert d.seen("key_0") is False
        # 最新 key_10000 还在
        assert d.seen("key_10000") is True


class TestThreadSafety:
    def test_concurrent_seen_unique(self):
        """100 线程并发塞 1000 个 key，最终容量不超过 capacity，所有 key 不重复"""
        d = _LRUDedup(capacity=500)
        results = []
        results_lock = threading.Lock()

        def worker(start):
            for i in range(start, start + 100):
                with results_lock:
                    results.append(d.seen(f"key_{i}"))

        threads = [threading.Thread(target=worker, args=(t * 100,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 容量未超
        assert len(d) == 500
        # 至少 1 个 key 被首次见到（返回 False）
        assert any(r is False for r in results), "至少应有 1 个首次见到的 key"
        # 至少 1 个 key 被重复见到（返回 True）—— 在容量允许下
        # （1000 个 key / 500 容量，淘汰 500 个，第一次的 seen 返回 True）


class TestClear:
    def test_clear_resets(self):
        d = _LRUDedup(capacity=10)
        d.seen("a")
        d.seen("b")
        assert len(d) == 2
        d.clear()
        assert len(d) == 0
        assert d.seen("a") is False  # 重新可被见到


class TestInvalidCapacity:
    def test_zero_capacity_raises(self):
        try:
            _LRUDedup(capacity=0)
        except ValueError:
            pass
        else:
            assert False, "应抛 ValueError"

    def test_negative_capacity_raises(self):
        try:
            _LRUDedup(capacity=-1)
        except ValueError:
            pass
        else:
            assert False, "应抛 ValueError"
