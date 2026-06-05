"""
企业微信智能机器人长连接客户端 - aibot SDK

频道职责：仅接收用户问题、调用 RAG、回复答案。反馈回路**仍走飞书**。
群聊需要 @小光咖啡百科 才回复；私聊直接回复。
"""
import asyncio
import threading

from aibot import WSClient, WSClientOptions

from config.settings import settings
from src.handler import MessageHandler


class WeComWebSocket:
    """企业微信智能机器人长连接客户端"""

    def __init__(self):
        self.bot_id = settings.wecom_bot_id
        self.secret = settings.wecom_secret
        self.handler = MessageHandler()
        self._processed = {}
        self._dedup_lock = threading.Lock()
        self._client: WSClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.running = False

    def start(self):
        if not self.bot_id or not self.secret:
            print("WARN: 企业微信凭证未配置，跳过WebSocket连接")
            return

        opts = WSClientOptions(
            bot_id=self.bot_id,
            secret=self.secret,
        )
        self._client = WSClient(opts)
        self._client.on("message.text", self._on_text)
        self._client.on("connected", lambda: print("企业微信WebSocket已连接"))
        self._client.on("authenticated", lambda: print("企业微信鉴权成功"))
        self._client.on(
            "disconnected", lambda r: print(f"企业微信WebSocket已断开: {r}")
        )

        # aibot SDK 自带事件循环，放独立线程跑
        self._thread = threading.Thread(target=self._client.run, daemon=True)
        self._thread.start()
        self.running = True

    def _on_text(self, frame: dict) -> None:
        try:
            body = frame.get("body", {}) or {}
            msgid = body.get("msgid")
            chattype = body.get("chattype", "single")
            from_info = body.get("from", {}) or {}
            user_id = from_info.get("userid", "unknown")
            text = (body.get("text", {}) or {}).get("content", "").strip()

            if chattype == "group":
                if "小光咖啡百科" not in text:
                    return
                text = text.replace("@小光咖啡百科", "").strip()

            if not text:
                return

            with self._dedup_lock:
                if msgid and msgid in self._processed:
                    return
                if msgid:
                    self._processed[msgid] = True

            print(f"[WeCom] {chattype} {user_id}: {text}")

            answer, _ = self.handler.process_question(
                question=text, user_id=user_id, message_id=msgid
            )

            asyncio.create_task(
                self._reply_text(frame, msgid or "", answer)
            )
        except Exception as e:
            import traceback
            print(f"ERROR: 企业微信处理消息异常 {e}")
            traceback.print_exc()

    async def _reply_text(self, frame: dict, stream_id: str, text: str) -> None:
        if not self._client:
            return
        try:
            await self._client.reply_stream(
                frame, stream_id=stream_id, content=text, finish=True
            )
        except Exception as e:
            import traceback
            print(f"ERROR: 企业微信回复失败 {e}")
            traceback.print_exc()

    def stop(self):
        if self._client:
            try:
                self._client.disconnect()
            except Exception as e:
                print(f"WARN: 断开企业微信连接异常 {e}")
        self.running = False


class WeComWSRunner:
    def __init__(self):
        self.ws = WeComWebSocket()
        self.thread: threading.Thread | None = None

    def run(self):
        self.ws.start()
        if self.ws.running:
            self.thread = threading.Thread(target=self._wait, daemon=True)
            self.thread.start()

    def _wait(self):
        while self.ws.running:
            import time
            time.sleep(1)

    def stop(self):
        self.ws.stop()
