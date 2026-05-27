"""
Feishu Client 模块测试
"""
import pytest
from src.feishu_client import FeishuClient


class TestFeishuClient:
    """FeishuClient 测试"""

    def setup_method(self):
        self.client = FeishuClient()

    def test_client_init(self):
        """测试客户端初始化"""
        assert self.client is not None

    def test_send_text_without_config(self):
        """测试无配置时发送"""
        result = self.client.send_text("test_user", "test message")
        assert result is False