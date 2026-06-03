"""
FeishuWebSocket 命令解析测试
"""
import pytest
from config.settings import settings
from src.feishu_ws import FeishuWebSocket


class TestBindAdminLock:
    """绑定管理员命令的安全锁测试 —— 防止已绑定后被任意用户劫持"""

    def setup_method(self):
        self.ws = FeishuWebSocket()
        self._orig_open_id = settings.feishu_admin_open_id
        self._orig_chat_id = settings.feishu_admin_chat_id

    def teardown_method(self):
        settings.feishu_admin_open_id = self._orig_open_id
        settings.feishu_admin_chat_id = self._orig_chat_id

    def test_refuse_when_open_id_already_set(self):
        """已设置 open_id 时，绑定命令必须拒绝"""
        settings.feishu_admin_open_id = "ou_existing_admin"
        settings.feishu_admin_chat_id = ""

        handled, reply = self.ws._try_handle_command(
            "绑定管理员", user_id="ou_attacker", message_id="m1"
        )

        assert handled is True
        assert "无法再次绑定" in reply
        # 攻击者的 open_id 不应被写入
        assert settings.feishu_admin_open_id == "ou_existing_admin"

    def test_refuse_when_chat_id_already_set(self):
        """已设置 chat_id 时，绑定命令也必须拒绝（避免 open_id 覆盖 chat_id 通道）"""
        settings.feishu_admin_open_id = ""
        settings.feishu_admin_chat_id = "oc_existing_group"

        handled, reply = self.ws._try_handle_command(
            "我是管理员", user_id="ou_attacker", message_id="m1"
        )

        assert handled is True
        assert "无法再次绑定" in reply
        assert settings.feishu_admin_chat_id == "oc_existing_group"

    def test_refuse_returns_pointer_to_env_editing(self):
        """拒绝消息应包含更换管理员的操作指引"""
        settings.feishu_admin_open_id = "ou_existing"

        _, reply = self.ws._try_handle_command(
            "绑定管理员", user_id="ou_attacker", message_id="m1"
        )

        assert ".env" in reply
        assert "FEISHU_ADMIN_OPEN_ID" in reply
