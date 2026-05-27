"""
Notifier 模块测试
"""
import pytest
from src.notifier import Notifier


class TestNotifier:
    """Notifier 测试"""

    def setup_method(self):
        self.notifier = Notifier()

    def test_notify_init(self):
        """测试通知器初始化"""
        assert self.notifier is not None

    def test_notify_without_webhook(self):
        """测试无webhook配置"""
        result = self.notifier.notify("测试标题", "测试内容")
        assert result is False