"""
飞书客户端 - lark-oapi SDK

lark.Client 跨线程不安全：内部用 asyncio.Lock 绑专属 loop，跨线程直接调
行为未定义。所有 reply_text / send_message / send_card 都通过 FeishuIOWorker
单线程 worker 串行化。
"""
import json
from typing import Optional
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from lark_oapi.api.im.v1.model.reply_message_request_body import ReplyMessageRequestBody
from lark_oapi.api.im.v1.model.create_message_request_body import CreateMessageRequestBody
from config.settings import settings
from src.feishu_io import FeishuIOWorker, get_feishu_io


class FeishuClient:
    """飞书客户端"""

    def __init__(self, io: Optional[FeishuIOWorker] = None):
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.client = None
        self._io = io  # 不传则同步直调（单测用）

        if self.app_id and self.app_secret:
            self.client = lark.Client.builder()                 .app_id(self.app_id)                 .app_secret(self.app_secret)                 .build()

    def send_message(self, receive_id: str, msg_type: str, content: dict) -> bool:
        """发送消息（走 IO worker）"""
        if self._io is not None:
            return self._io.submit(self._do_send_message, receive_id, msg_type, content)
        return self._do_send_message(receive_id, msg_type, content)

    def _do_send_message(self, receive_id: str, msg_type: str, content: dict) -> bool:
        """实际 lark.Client 调用（必须在 IO worker 线程内）"""
        if not self.client:
            print("WARN: 飞书客户端未初始化，跳过发送")
            return False

        try:
            receive_id_type = self._detect_receive_id_type(receive_id)
            body = CreateMessageRequestBody.builder() \
                .receive_id(receive_id) \
                .msg_type(msg_type) \
                .content(json.dumps(content, ensure_ascii=False)) \
                .build()

            request = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
                .request_body(body) \
                .build()

            response = self.client.im.v1.message.create(request)

            if response.code == 0:
                return True
            else:
                print(f"ERROR: 飞书发送失败 {response.msg}")
                return False

        except Exception as e:
            print(f"ERROR: 飞书发送异常 {e}")
            return False

    @staticmethod
    def _detect_receive_id_type(receive_id: str) -> str:
        """根据 ID 前缀推断 receive_id_type"""
        if receive_id.startswith("ou_"):
            return "open_id"
        if receive_id.startswith("oc_"):
            return "chat_id"
        if receive_id.startswith("u_"):
            return "user_id"
        if "@" in receive_id:
            return "email"
        return "open_id"  # 默认

    def send_text(self, receive_id: str, text: str) -> bool:
        """发送文本消息"""
        return self.send_message(
            receive_id=receive_id,
            msg_type="text",
            content={"text": text}
        )

    def send_card(self, receive_id: str, card: dict) -> bool:
        """发送 interactive 卡片（msg_type=interactive）"""
        return self.send_message(
            receive_id=receive_id,
            msg_type="interactive",
            content=card
        )

    def reply_text(self, message_id: str, text: str) -> bool:
        """回复消息（走 IO worker）"""
        if self._io is not None:
            return self._io.submit(self._do_reply_text, message_id, text)
        return self._do_reply_text(message_id, text)

    def _do_reply_text(self, message_id: str, text: str) -> bool:
        """实际 reply API 调用（必须在 IO worker 线程内）"""
        if not self.client:
            print("WARN: 飞书客户端未初始化，跳过回复")
            return False

        try:
            content_str = json.dumps({"text": text}, ensure_ascii=False)
            body = ReplyMessageRequestBody.builder()                 .msg_type("text")                 .content(content_str)                 .build()

            request = ReplyMessageRequest.builder()                 .message_id(message_id)                 .request_body(body)                 .build()

            response = self.client.im.v1.message.reply(request)

            if response.code == 0:
                return True
            else:
                print(f"ERROR: 飞书回复失败 {response.msg}")
                return False

        except Exception as e:
            print(f"ERROR: 飞书回复异常 {e}")
            return False
