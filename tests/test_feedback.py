"""
Feedback 模块测试
"""
import pytest
import tempfile
import shutil
from pathlib import Path
from src.feedback import FeedbackCollector


class TestFeedbackCollector:
    """FeedbackCollector 测试"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.collector = FeedbackCollector(Path(self.temp_dir))

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_collect(self):
        """测试收集反馈"""
        self.collector.collect("什么是咖啡", "咖啡是一种饮料", "no_context")
        feedbacks = list(self.collector.feedback_dir.glob("*.jsonl"))
        assert len(feedbacks) > 0

    def test_get_recent_feedback(self):
        """测试获取最近反馈"""
        self.collector.collect("问题1", "回答1", "no_context")
        feedbacks = self.collector.get_recent_feedback(limit=5)
        assert len(feedbacks) > 0