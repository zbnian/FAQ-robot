"""
单例 indexer + 锁语义测试

这些测试在 host（Windows）上无法运行，因为 sentence-transformers + faiss 的
DLL 加载在当前 Python 环境有兼容问题。本机只做 py_compile 检查。

在 NAS / Docker 容器内执行：
    docker exec faq-robot py -X utf8 -m pytest tests/test_reindex_singleton.py -v
"""
import threading
from src.indexer import FAISSIndexer, Chunk, get_indexer


class TestIndexerSingleton:
    def setup_method(self):
        import src.indexer as idx_mod
        idx_mod._indexer_instance = None

    def teardown_method(self):
        import src.indexer as idx_mod
        idx_mod._indexer_instance = None

    def test_get_indexer_returns_same_instance(self):
        a = get_indexer()
        b = get_indexer()
        assert a is b

    def test_get_indexer_thread_safe(self):
        results = []

        def grab():
            results.append(get_indexer())

        threads = [threading.Thread(target=grab) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        first = results[0]
        assert all(r is first for r in results), "并发调用必须返回同一实例"


class TestIndexerLockSemantics:
    def setup_method(self):
        self.idx = get_indexer()

    def teardown_method(self):
        # 兜底清理
        if self.idx._rebuilding:
            try:
                self.idx.release_write()
            except Exception:
                pass

    def test_read_lock_acquired_when_idle(self):
        lock = self.idx.acquire_read()
        assert lock is not None
        lock.release()

    def test_read_lock_rejected_during_rebuild(self):
        self.idx.acquire_write()
        try:
            assert self.idx.is_rebuilding() is True
            assert self.idx.acquire_read() is None
        finally:
            self.idx.release_write()

    def test_read_lock_works_again_after_write_released(self):
        self.idx.acquire_write()
        self.idx.release_write()
        lock = self.idx.acquire_read()
        assert lock is not None
        lock.release()

    def test_search_returns_empty_during_rebuild(self):
        self.idx.chunks = [Chunk("t", "c", "f.md")]
        self.idx.acquire_write()
        try:
            results = self.idx.search("任意查询", top_k=3)
            assert results == []
        finally:
            self.idx.release_write()

    def test_concurrent_readers_share_lock(self):
        lock_a = self.idx.acquire_read()
        lock_b = self.idx.acquire_read()
        assert lock_a is not None
        assert lock_b is not None
        lock_a.release()
        lock_b.release()

    def test_write_blocks_subsequent_read(self):
        self.idx.acquire_write()
        try:
            assert self.idx.acquire_read() is None
        finally:
            self.idx.release_write()


class TestRetrieverUsesSharedIndexer:
    def setup_method(self):
        import src.indexer as idx_mod
        idx_mod._indexer_instance = None

    def teardown_method(self):
        import src.indexer as idx_mod
        idx_mod._indexer_instance = None

    def test_retriever_uses_singleton_indexer(self):
        from src.retriever import Retriever
        shared = get_indexer()
        r = Retriever()
        assert r.indexer is shared
