"""
飞书客户端 - lark-oapi SDK
"""
import json
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from lark_oapi.api.im.v1.model.reply_message_request_body import ReplyMessageRequestBody
from config.settings import settings


class FeishuClient:
    """飞书客户端"""

    def __init__(self):
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.client = None

        if self.app_id and self.app_secret:
            self.client = lark.Client.builder()                 .app_id(self.app_id)                 .app_secret(self.app_secret)                 .build()

    def send_message(self, receive_id: str, msg_type: str, content: dict) -> bool:
        """发送消息"""
        if not self.client:
            print("WARN: 飞书客户端未初始化，跳过发送")
            return False

        try:
            request = CreateMessageRequest.builder()
            request.receive_id(receive_id)
            request.msg_type(msg_type)
            request.content(content)

            response = self.client.im.v1.message.create(request.build())

            if response.code == 0:
                return True
            else:
                print(f"ERROR: 飞书发送失败 {response.msg}")
                return False

        except Exception as e:
            print(f"ERROR: 飞书发送异常 {e}")
            return False

    def send_text(self, receive_id: str, text: str) -> bool:
        """发送文本消息"""
        return self.send_message(
            receive_id=receive_id,
            msg_type="text",
            content={"text": text}
        )

    def send_card(self, receive_id: str, card: dict) -> bool:
        """发送 interactive 卡片（msg_type=interactive）"""
        # 飞书要求 content 是 JSON 字符串
        return self.send_message(
            receive_id=receive_id,
            msg_type="interactive",
            content={"card": json.dumps(card, ensure_ascii=False)}
        )

    def reply_text(self, message_id: str, text: str) -> bool:
        """回复消息"""
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
