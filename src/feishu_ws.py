"""
飞书 WebSocket 客户端 - lark-oapi SDK WebSocket长连接
"""
import json
import threading
import time
import lark_oapi as lark
from lark_oapi.ws import Client as WsClient
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1, P2ImChatAccessEventBotP2pChatEnteredV1
from config.settings import settings
from src.handler import MessageHandler


class FeishuWebSocket:
    """飞书WebSocket长连接客户端"""

    def __init__(self):
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.ws_client = None
        self.handler = MessageHandler()
        self.running = False
        self._processed_messages = {}
        self._dedup_lock = threading.Lock()

    def start(self):
        """启动WebSocket连接"""
        if not self.app_id or not self.app_secret:
            print("WARN: 飞书凭证未配置，跳过WebSocket连接")
            return

        try:
            # 创建事件处理器
            event_handler = EventDispatcherHandler.builder(
                "",  # encrypt_key（未加密则留空）
                ""   # verification_token（留空）
            ).register_p2_im_message_receive_v1(self._on_message_receive) \
             .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(self._on_chat_entered)

            # 创建WebSocket客户端
            self.ws_client = WsClient(
                app_id=self.app_id,
                app_secret=self.app_secret,
                log_level=lark.LogLevel.INFO,
                event_handler=event_handler.build()
            )

            self.ws_client.start()

            self.running = True
            print("飞书WebSocket已连接")

        except Exception as e:
            print(f"ERROR: 飞书WebSocket连接失败 {e}")

    def _on_message_receive(self, data: P2ImMessageReceiveV1) -> None:
        """
        处理接收到的消息事件

        Args:
            data: P2ImMessageReceiveV1 事件对象
        """
        try:
            # data.event 是 P2ImMessageReceiveV1Data 对象
            event = data.event
            if event is None:
                return

            # 获取消息内容
            message = event.message
            if not message:
                return

            # message 是 Message object, message_type 是属性
            message_type = getattr(message, 'message_type', None)
            if message_type != "text":
                return

            # content 是字符串，需要解析
            content_str = getattr(message, 'content', '{}')
            if isinstance(content_str, str):
                content = json.loads(content_str)
            else:
                content = content_str

            text = content.get("text", "").strip()
            message_id = getattr(message, 'message_id', None)
            chat_type = getattr(message, 'chat_type', 'p2p')
            sender = event.sender if hasattr(event, 'sender') else None
            user_id = None
            if sender:
                sender_id = getattr(sender, 'sender_id', None)
                if sender_id:
                    user_id = getattr(sender_id, 'open_id', None)

            # 检查mentions字段
            mentions = getattr(message, 'mentions', None)
            mention_names = []
            if mentions:
                for m in mentions:
                    name = getattr(m, 'name', None)
                    if name:
                        mention_names.append(name)

            print(f"[原始消息] user={user_id}, message_id={message_id}, chat_type={chat_type}, text={text}, mentions={mention_names}")

            # 私信(p2p)不需要@mention，群聊(group)需要@小光咖啡百科才响应
            if chat_type == 'group':
                if "小光咖啡百科" not in mention_names:
                    return
                # 群聊时移除@占位符
                text = text.replace("@_user_1", "").strip()

            if not text:
                return

            # 消息去重（加锁保证线程安全）
            with self._dedup_lock:
                if message_id and message_id in self._processed_messages:
                    return
                self._processed_messages[message_id] = True

                print(f"[收到消息] {user_id}: {text}")

                answer, _ = self.handler.process_question(
                    question=text,
                    user_id=user_id,
                    message_id=message_id
                )

                if message_id and self.handler.feishu.client:
                    self.handler.feishu.reply_text(message_id, answer)

        except Exception as e:
            import traceback
            print(f"ERROR: 处理消息异常 {e}")
            traceback.print_exc()

    def _on_chat_entered(self, data: P2ImChatAccessEventBotP2pChatEnteredV1) -> None:
        """处理用户进入会话事件"""
        try:
            print("[用户进入会话]")
        except Exception as e:
            print(f"ERROR: 处理进入会话事件异常 {e}")

    def stop(self):
        """停止WebSocket连接"""
        self.running = False
        if self.ws_client:
            print("飞书WebSocket已断开")


class FeishuWSRunner:
    """飞书WebSocket运行器"""

    def __init__(self):
        self.ws = FeishuWebSocket()
        self.thread = None

    def run(self):
        """在新线程中运行WebSocket"""
        self.ws.start()
        if self.ws.running:
            self.thread = threading.Thread(target=self._wait, daemon=True)
            self.thread.start()

    def _wait(self):
        """等待连接断开"""
        while self.ws.running:
            time.sleep(1)

    def stop(self):
        """停止WebSocket"""
        self.ws.stop()
