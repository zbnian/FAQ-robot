"""
Retriever 单例 + lazy init 加锁 + chunk._idx 预分配测试

回归目标：
1. 飞书 / 企微 runner 各 new Retriever 共享同一份 indexer
2. _ensure_index / _get_expander 并发首次只执行一次
3. retrieve_with_expansion 用 chunk._idx 直接 O(1) 合并结果

这些测试在 host（Windows）上无法运行，因为 sentence-transformers + faiss 的
DLL 加载在当前 Python 环境有兼容问题 / 加载极慢。本机只做 py_compile 检查。

在 NAS / Docker 容器内执行：
    docker exec faq-robot py -X utf8 -m pytest tests/test_retriever_singleton.py -v
"""
import threading
from unittest.mock import MagicMock, patch

import src.retriever as ret_mod


def _import_factory():
    """延迟 import：避免 host 上 sentence-transformers / faiss 加载极慢"""
    from src.retriever import Retriever, get_retriever
    return Retriever, get_retriever


class TestRetrieverSingleton:
    def setup_method(self):
        ret_mod._retriever_instance = None

    def teardown_method(self):
        ret_mod._retriever_instance = None

    def test_factory_returns_same_instance(self):
        _, get_retriever = _import_factory()
        a = get_retriever()
        b = get_retriever()
        assert a is b

    def test_factory_thread_safe(self):
        _, get_retriever = _import_factory()
        results = []

        def grab():
            results.append(get_retriever())

        threads = [threading.Thread(target=grab) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        first = results[0]
        assert all(r is first for r in results), "并发调用必须返回同一实例"


class TestRetrieverLazyInitLock:
    """_ensure_index / _get_expander 必须线程安全：并发首次只 load 一次"""

    def setup_method(self):
        # 注入 mock indexer（避免真 load sentence-transformers + faiss）
        self.mock_indexer = MagicMock()
        self.mock_indexer.chunks = []
        ret_mod._retriever_instance = Retriever(
            indexer=self.mock_indexer,
            enable_expansion=True,
        )

    def teardown_method(self):
        ret_mod._retriever_instance = None

    def test_concurrent_ensure_index_loads_once(self):
        """20 线程并发 _ensure_index，load_index 必须只调一次"""
        call_count = 0
        call_lock = threading.Lock()

        def slow_load():
            nonlocal call_count
            with call_lock:
                call_count += 1
            import time
            time.sleep(0.05)  # 模拟首次 IO 耗时

        self.mock_indexer.load_index = slow_load
        r = ret_mod._retriever_instance

        threads = [threading.Thread(target=r._ensure_index) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert call_count == 1, f"load_index 应只调一次，实调 {call_count} 次"
        assert r._index_loaded is True

    def test_concurrent_get_expander_creates_once(self):
        """20 线程并发 _get_expander，QueryExpansionLearner() 必须只 new 一次"""
        r = ret_mod._retriever_instance

        with patch("src.auto_optimizer.QueryExpansionLearner") as mock_learner:
            mock_learner.side_effect = lambda: MagicMock(name=f"learner_{id(r)}")

            results = []
            results_lock = threading.Lock()

            def grab():
                exp = r._get_expander()
                with results_lock:
                    results.append(exp)

            threads = [threading.Thread(target=grab) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert mock_learner.call_count == 1, f"QueryExpansionLearner 应只 new 一次，实 new {mock_learner.call_count} 次"
            assert all(e is results[0] for e in results), "所有线程必须拿到同一 expander"


class TestChunkIdxPreAllocation:
    """indexer.load_knowledge_base 必须给每个 Chunk 预分配 _idx"""

    def test_load_knowledge_base_assigns_idx(self, tmp_path):
        # 延迟 import：避免 host 上 sentence-transformers / faiss 加载极慢
        from src.indexer import FAISSIndexer

        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "a.md").write_text(
            "# A\n## A1\nA1 content\n## A2\nA2 content\n# B\n## B1\nB1 content\n",
            encoding="utf-8",
        )

        idx = FAISSIndexer()
        chunks = idx.load_knowledge_base(kb)
        # 顺序应与原 chunks 列表索引一致
        for i, c in enumerate(chunks):
            assert hasattr(c, "_idx"), f"chunk {i} 缺 _idx"
            assert c._idx == i, f"chunk {i}._idx={c._idx}，应为 {i}"
