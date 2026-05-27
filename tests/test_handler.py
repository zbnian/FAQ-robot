"""
Handler 模块测试
"""
import pytest
from src.handler import MessageHandler


class TestMessageHandler:
    """MessageHandler 测试"""

    def setup_method(self):
        self.handler = MessageHandler()

    def test_handler_init(self):
        """测试处理器初始化"""
        assert self.handler is not None
        assert self.handler.retriever is not None
        assert self.handler.generator is not None