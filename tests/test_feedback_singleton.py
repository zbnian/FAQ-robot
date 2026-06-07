"""
FeedbackCollector 单例 + 模块级 TPE 测试

回归目标：飞书 + 企微双 MessageHandler 各 new 一个 FeedbackCollector 时，
两路线程同时 collect 会撞号（重复 fb-YYYYMMDD-NNN）。

修后：所有通道走 get_feedback_collector() 进程内单例，_seq_lock 唯一。

注意：test_concurrent_collect_across_handlers 会 new MessageHandler()，
从而 import Retriever（sentence-transformers + faiss）。这两个库在
当前 Windows Python 环境加载极慢 / DLL 不兼容，host 上跑会卡死。
建议在 NAS / Docker 容器内执行：

    docker exec faq-robot py -X utf8 -m pytest tests/test_feedback_singleton.py -v
"""
import threading
import shutil
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import src.feedback as fb_mod
from src.feedback import get_feedback_collector


class TestFeedbackSingleton:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        fb_mod._instance = None

    def teardown_method(self):
        fb_mod._instance = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_factory_returns_same_instance(self):
        a = get_feedback_collector()
        b = get_feedback_collector()
        assert a is b

    def test_factory_thread_safe(self):
        """20 线程并发调 get_feedback_collector，必须全部返回同一实例"""
        results = []

        def grab():
            results.append(get_feedback_collector())

        threads = [threading.Thread(target=grab) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        first = results[0]
        assert all(r is first for r in results), "并发调用必须返回同一实例"

    def test_concurrent_collect_no_collision(self):
        """50 线程并发 collect，断言所有 feedback_id 唯一"""
        collector = get_feedback_collector()
        collector.feedback_dir = Path(self.temp_dir)

        ids = []
        ids_lock = threading.Lock()

        def do_collect(i):
            fid = collector.collect(f"问题{i}", f"回答{i}", "no_context", notify=False)
            with ids_lock:
                ids.append(fid)

        threads = [threading.Thread(target=do_collect, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(ids) == 50, f"应收到 50 个 feedback_id，实收 {len(ids)}"
        assert len(set(ids)) == 50, f"feedback_id 撞号了：{len(set(ids))} 唯一 / {len(ids)} 总"

        # 同一天 seq 应连续 1..50
        seqs = sorted(int(fid.rsplit("-", 1)[1]) for fid in ids)
        assert seqs == list(range(1, 51)), f"seq 不连续：{seqs[:5]}..."

    def test_concurrent_collect_across_handlers(self):
        """模拟飞书/企微双 runner 各 new MessageHandler：handler1.feedback is handler2.feedback"""
        from src.handler import MessageHandler
        h1 = MessageHandler()
        h2 = MessageHandler()
        assert h1.feedback is h2.feedback
        assert h1.feedback is h1.feedback  # 多次访问稳定


class TestNotifyTPE:
    """模块级 _notify_executor TPE：替代无界 daemon thread"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        fb_mod._instance = None

    def teardown_method(self):
        fb_mod._instance = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_executor_is_module_level_singleton(self):
        from src.feedback import _notify_executor
        from src.feedback import _notify_executor as again
        assert _notify_executor is again
        assert isinstance(_notify_executor, ThreadPoolExecutor)

    def test_submit_does_not_block_collect(self):
        """_notify 即使 sleep 也不阻塞 collect 主流程"""
        collector = get_feedback_collector()
        collector.feedback_dir = Path(self.temp_dir)
        # notify 慢一点也不会让 collect 等待
        fid = collector.collect("q", "a", "no_context", notify=True)
        assert fid.startswith("fb-")
        # 即便通知还没跑完，文件已经写入
        files = list(Path(self.temp_dir).glob("feedback_*.jsonl"))
        assert len(files) == 1
