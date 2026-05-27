"""
Scheduler 模块测试
"""
import pytest
from src.scheduler import IndexScheduler


class TestIndexScheduler:
    """IndexScheduler 测试"""

    def setup_method(self):
        self.scheduler = IndexScheduler()

    def test_scheduler_init(self):
        """测试调度器初始化"""
        assert self.scheduler is not None
        assert self.scheduler.indexer is not None