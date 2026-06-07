"""
RAG 槽位测试

回归目标：验证 _rag_pool 的 try_acquire_rag_slot / release_rag_slot
在并发场景下的正确性。
"""
import threading

import src._rag_pool as rp


class TestBasicAcquireRelease:
    def setup_method(self):
        # 重置模块状态（防止其他测试污染）
        rp._in_flight_count = 0

    def test_first_acquire_succeeds(self):
        assert rp.try_acquire_rag_slot() is True
        assert rp.get_in_flight_count() == 1

    def test_release_decrements(self):
        rp.try_acquire_rag_slot()
        rp.release_rag_slot()
        assert rp.get_in_flight_count() == 0

    def test_release_below_zero_protected(self):
        """release 比 acquire 多不能把 count 推到负数"""
        rp.release_rag_slot()
        rp.release_rag_slot()
        assert rp.get_in_flight_count() == 0


class TestCapacityLimit:
    def setup_method(self):
        rp._in_flight_count = 0

    def test_max_in_flight_constant(self):
        assert rp.MAX_IN_FLIGHT == 11  # 1 跑 + 10 排

    def test_11th_acquire_fails(self):
        """前 11 次成功，第 12 次被拒"""
        for i in range(rp.MAX_IN_FLIGHT):
            assert rp.try_acquire_rag_slot() is True, f"第 {i+1} 次 acquire 应成功"
        assert rp.get_in_flight_count() == rp.MAX_IN_FLIGHT
        # 第 12 次失败
        assert rp.try_acquire_rag_slot() is False
        assert rp.get_in_flight_count() == rp.MAX_IN_FLIGHT  # 计数不变

    def test_release_makes_room(self):
        # 占满
        for _ in range(rp.MAX_IN_FLIGHT):
            assert rp.try_acquire_rag_slot() is True
        assert rp.try_acquire_rag_slot() is False
        # 释放一个
        rp.release_rag_slot()
        # 又能拿了
        assert rp.try_acquire_rag_slot() is True
        # 再满
        assert rp.try_acquire_rag_slot() is False


class TestThreadSafety:
    def setup_method(self):
        rp._in_flight_count = 0

    def test_concurrent_acquire_never_exceeds_max(self):
        """50 线程并发 acquire，max_in_flight 不能被突破"""
        acquired = []
        acquired_lock = threading.Lock()

        def worker():
            ok = rp.try_acquire_rag_slot()
            if ok:
                with acquired_lock:
                    acquired.append(threading.get_ident())

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 成功 acquire 的线程数 == MAX_IN_FLIGHT（不可能多于）
        assert len(acquired) == rp.MAX_IN_FLIGHT
        # count 也对齐
        assert rp.get_in_flight_count() == rp.MAX_IN_FLIGHT

    def test_acquire_release_churn(self):
        """100 线程并发做 acquire → release 循环，count 最终归 0"""
        errors = []

        def worker():
            try:
                for _ in range(100):
                    if rp.try_acquire_rag_slot():
                        rp.release_rag_slot()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"线程异常: {errors}"
        # 全部配对 release 后 count 必须归 0
        assert rp.get_in_flight_count() == 0
