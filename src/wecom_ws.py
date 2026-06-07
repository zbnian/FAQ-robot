"""
企业微信智能机器人长连接客户端 - aibot SDK

频道职责：仅接收用户问题、调用 RAG、回复答案。反馈回路**仍走飞书**。
群聊需要 @小光咖啡百科 才回复；私聊直接回复。

架构：aibot SDK 内部用 asyncio.new_event_loop() + run_forever() 跑在独立
守护线程。_on_text 在该 loop 线程被调，**不能**阻塞（否则 SDK 不能 ping /
不能重连 / 不能处理新消息）。

修后链路：
  _on_text (loop 线程) → 解析 + dedup → asyncio.create_task(_handle_async)
                                            ↓
  _handle_async (loop 线程)
    - semaphore 满了：先 reply_text "已收到，前面在处理"
    - 通过 asyncio.to_thread 把 RAG 派到 default executor（max_workers=1）
    - 每 5 个 token 跨线程调 reply_stream 推回 SDK loop
    - 流结束调 reply_stream(finish=True) 发最后一段
"""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from aibot import WSClient, WSClientOptions

from config.settings import settings
from src.handler import MessageHandler
from src._lru_dedup import _LRUDedup
from src._rag_pool import (
    try_acquire_rag_slot, release_rag_slot,
    get_in_flight_count, MAX_IN_FLIGHT,
)
from src.logger import logger

ACK_OVERLOAD = "系统繁忙，请稍后再试..."


class WeComWebSocket:
    """企业微信智能机器人长连接客户端"""

    # 每 N 个 token 推一次 SDK（避免每 token 触发 reply API 限流 30/min/会话）
    STREAM_PUSH_INTERVAL = 5

    def __init__(self):
        self.bot_id = settings.wecom_bot_id
        self.secret = settings.wecom_secret
        self.handler = MessageHandler()
        self._dedup = _LRUDedup(capacity=10000)
        self._dedup_lock = threading.Lock()  # 兼容旧调用
        self._client: WSClient | None = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.running = False

    def start(self):
        if not self.bot_id or not self.secret:
            logger.warning("企业微信凭证未配置，跳过WebSocket连接")
            return

        opts = WSClientOptions(
            bot_id=self.bot_id,
            secret=self.secret,
        )
        self._client = WSClient(opts)
        self._client.on("message.text", self._on_text)
        self._client.on("connected", lambda: logger.info("企业微信WebSocket已连接"))
        self._client.on("authenticated", lambda: logger.info("企业微信鉴权成功"))
        self._client.on(
            "disconnected", lambda r: logger.info(f"企业微信WebSocket已断开: {r}")
        )

        # aibot SDK 自带事件循环，放独立线程跑
        self._thread = threading.Thread(target=self._client.run, daemon=True)
        self._thread.start()
        self.running = True

    def _on_text(self, frame: dict) -> None:
        """SDK loop 线程上被调。必须快速 return，不跑 RAG。"""
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
                if msgid and self._dedup.seen(msgid):
                    return

            logger.info(f"[WeCom] {chattype} {user_id}: {text}")

            # 抓 SDK loop 引用：aibot SDK 不在 client 上挂 _loop 属性，
            # 但 _on_text 跑在 SDK loop 线程上，get_running_loop() 拿得到。
            # 存到 self 上，让 default executor 里的 RAG worker 能 run_coroutine_threadsafe
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = None
            if self._loop is None:
                # 不在 asyncio 上下文：兜底同步（不应该走到这里）
                self._run_rag_sync(frame, body, text, msgid, user_id)
                return

            # 限流闸移到 _handle_async（async），_on_text 是 sync 不能 await
            asyncio.create_task(self._handle_async(frame, body, text, msgid, user_id))
        except Exception as e:
            logger.exception("企业微信 _on_text 异常: %s", e)

    async def _handle_async(self, frame: dict, body: dict, text: str,
                             msgid: Optional[str], user_id: str) -> None:
        """限流 + 真流式：抢 RAG 槽位（飞书 + 企微共享），满了先 ack 过载告知。"""
        if not self._client:
            return
        # 限流闸：> MAX_IN_FLIGHT 时直接拒绝
        if not try_acquire_rag_slot():
            logger.warning(
                f"企微 RAG 队列已满（in_flight={get_in_flight_count()}/{MAX_IN_FLIGHT}），"
                f"拒绝 msgid={msgid}"
            )
            try:
                await self._client.reply_text(frame, ACK_OVERLOAD)
            except Exception as e:
                logger.warning("过载 ack 发送失败: %s", e)
            return
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._run_rag_with_stream, frame, body, text, msgid, user_id),
                timeout=600,
            )
        except asyncio.TimeoutError:
            logger.error("RAG 超时 msgid=%s", msgid)
        except Exception as e:
            logger.exception("RAG 执行失败: %s", e)

    def _run_rag_with_stream(self, frame: dict, body: dict, text: str,
                              msgid: Optional[str], user_id: str) -> None:
        """跑在 default executor（独立线程）。每个 token 跨线程送回 SDK loop。"""
        accumulated: list[str] = []

        def on_token(tok: str) -> None:
            accumulated.append(tok)
            # 跨线程送回 SDK loop：每 N 个 token 推一次
            if len(accumulated) % self.STREAM_PUSH_INTERVAL == 0:
                self._schedule_reply_stream(
                    frame, msgid or "", "".join(accumulated), finish=False
                )

        try:
            self.handler.process_question_streaming(
                question=text, user_id=user_id, message_id=msgid, on_token=on_token
            )
        finally:
            # 推最后一段（finish=True 收尾）
            self._schedule_reply_stream(
                frame, msgid or "", "".join(accumulated), finish=True, wait=True
            )
            # 流结束（成功/异常）都释放槽位
            release_rag_slot()

    def _schedule_reply_stream(self, frame: dict, stream_id: str, content: str,
                                finish: bool, wait: bool = False) -> None:
        """跨线程把 reply_stream 送回 SDK loop。wait=True 时等回执（最后一段）。"""
        if not self._client or frame is None:
            return
        coro = self._client.reply_stream(
            frame, stream_id=stream_id, content=content, finish=finish
        )
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        if wait:
            try:
                future.result(timeout=10)
            except Exception as e:
                logger.warning("reply_stream 收尾失败: %s", e)

    def _run_rag_sync(self, frame, body, text, msgid, user_id) -> None:
        """兜底：不在 asyncio 上下文时同步跑（非典型路径，仅为不丢消息）"""
        answer, _ = self.handler.process_question(
            question=text, user_id=user_id, message_id=msgid
        )
        if self._client:
            try:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(
                        self._client.reply_stream(
                            frame, stream_id=msgid or "", content=answer, finish=True
                        )
                    )
                finally:
                    loop.close()
            except Exception as e:
                logger.warning("同步兜底 reply 失败: %s", e)

    def stop(self):
        if self._client:
            try:
                self._client.disconnect()
            except Exception as e:
                logger.warning("断开企业微信连接异常: %s", e)
        self.running = False


class WeComWSRunner:
    def __init__(self):
        self.ws = WeComWebSocket()
        self.thread: Optional[threading.Thread] = None

    def run(self):
        self.ws.start()
        if self.ws.running:
            # 关键：把 SDK loop 暴露给 ws（_on_text 在 loop 上跑时 get_running_loop 即此）
            # aibot SDK 内部用 _thread.start() 后 _loop = self._client._loop
            # 这里只能取 ws._loop（启动后由 _on_text 第一次被调时填充）
            self.thread = threading.Thread(target=self._wait, daemon=True)
            self.thread.start()

    def _wait(self):
        # 等 SDK 起来后再抓 loop（_on_text 第一次被调时填充）
        import time
        # 实际上 _on_text 在 self._client.run() 内部已经绑了 loop，
        # 我们需要从 ws._loop 拿；ws 内部 _schedule_reply_stream 也会兜底 None
        # 显式抓一次：SDK 会在其 daemon thread 上创建 _loop
        deadline = time.time() + 10
        while time.time() < deadline:
            loop = getattr(self.ws._client, "_loop", None) or getattr(self.ws._client, "loop", None)
            if loop is not None:
                self.ws._loop = loop
                break
            time.sleep(0.1)

        # 显式 set default executor：max_workers=1，与 RAG 限流对齐
        # （不显式 set 的话 default 是 ThreadPoolExecutor 默认 cpu*5）
        if self.ws._loop is not None:
            try:
                self.ws._loop.set_default_executor(
                    ThreadPoolExecutor(max_workers=1, thread_name_prefix="wecom-rag")
                )
            except Exception as e:
                logger.warning("set_default_executor 失败: %s", e)

        while self.ws.running:
            time.sleep(1)

    def stop(self):
        self.ws.stop()
