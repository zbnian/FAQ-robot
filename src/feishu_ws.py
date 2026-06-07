"""
飞书 WebSocket 客户端 - lark-oapi SDK WebSocket长连接

修后链路：
  SDK 回调 _on_message_receive（SDK thread-pool 线程）
    - 解析 + dedup（同步，< 5ms）
    - 立即 FeishuIOWorker.submit(reply_text, "咖啡知识库为您查找中...") ack
    - 提交 RAG 到 rag_executor（max_workers=1，限流）
    - 满载排队时 ack "前面有任务在处理，请稍等"

飞书侧不流式（lark-oapi template_card 增量更新复杂 + ROI 低）：降级为
"ack + 一次性 reply"。RAG 跑完直接发完整答案。企微侧走真流式 reply_stream。
"""
import json
import threading
import time
import lark_oapi as lark
from lark_oapi.ws import Client as WsClient
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    P2ImChatAccessEventBotP2pChatEnteredV1,
)
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger
from config.settings import settings
from src.handler import MessageHandler
from src.feedback import FeedbackCollector, STATUS_PENDING, VALID_STATUSES
from src.feishu_io import get_feishu_io
from src._rag_pool import get_rag_executor
from src._lru_dedup import _LRUDedup
from src.logger import logger

ACK_BUSY = "已收到，前面有任务在处理，请稍等..."
ACK_LOOKUP = "查找中，请稍等..."


class FeishuWebSocket:
    """飞书WebSocket长连接客户端"""

    def __init__(self):
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.ws_client = None
        # 把 IO worker 注入 handler.feishu：所有 reply_text / send_message
        # 自动走 FeishuIOWorker 单线程队列
        from src.feishu_client import FeishuClient as _FeishuClientCls
        self.handler = MessageHandler()
        self.handler.feishu = _FeishuClientCls(io=get_feishu_io())
        self.feedback = self.handler.feedback
        self.feishu = self.handler.feishu
        self._rag_executor = get_rag_executor()
        self.running = False
        self._dedup = _LRUDedup(capacity=10000)
        self._dedup_lock = threading.Lock()  # _LRUDedup 内部已带锁；外锁为兼容旧调用

    def start(self):
        """启动WebSocket连接"""
        if not self.app_id or not self.app_secret:
            logger.warning("飞书凭证未配置，跳过WebSocket连接")
            return

        try:
            event_handler = EventDispatcherHandler.builder(
                "",  # encrypt_key
                ""   # verification_token
            ).register_p2_im_message_receive_v1(self._on_message_receive) \
             .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(self._on_chat_entered) \
             .register_p2_card_action_trigger(self._on_card_action_trigger)

            self.ws_client = WsClient(
                app_id=self.app_id,
                app_secret=self.app_secret,
                log_level=lark.LogLevel.INFO,
                event_handler=event_handler.build()
            )

            self.ws_client.start()

            self.running = True
            logger.info("飞书WebSocket已连接")

        except Exception as e:
            logger.error("飞书WebSocket连接失败: %s", e)

    def _on_message_receive(self, data: P2ImMessageReceiveV1) -> None:
        try:
            event = data.event
            if event is None:
                return

            message = event.message
            if not message:
                return

            message_type = getattr(message, 'message_type', None)
            if message_type != "text":
                return

            content_str = getattr(message, 'content', '{}')
            if isinstance(content_str, str):
                content = json.loads(content_str)
            else:
                content = content_str

            text = content.get("text", "").strip()
            message_id = getattr(message, 'message_id', None)
            chat_type = getattr(message, 'chat_type', 'p2p')
            chat_id = getattr(message, 'chat_id', None)
            sender = event.sender if hasattr(event, 'sender') else None
            user_id = None
            if sender:
                sender_id = getattr(sender, 'sender_id', None)
                if sender_id:
                    user_id = getattr(sender_id, 'open_id', None)

            mentions = getattr(message, 'mentions', None)
            mention_names = []
            if mentions:
                for m in mentions:
                    name = getattr(m, 'name', None)
                    if name:
                        mention_names.append(name)

            logger.info(f"[原始消息] user={user_id}, chat={chat_id}, message_id={message_id}, chat_type={chat_type}, text={text}, mentions={mention_names}")

            if chat_type == 'group':
                if "小光咖啡百科" not in mention_names:
                    return
                text = text.replace("@_user_1", "").strip()

            if not text:
                return

            with self._dedup_lock:
                if message_id and self._dedup.seen(message_id):
                    return
                # 第一次见：_LRUDedup.seen 标记过；不需要再写 dict

            logger.info(f"[收到消息] {user_id}: {text}")

            # 命令解析（在 RAG 之前）
            handled, reply = self._try_handle_command(text, user_id, message_id)
            if handled:
                if reply and self.feishu.client:
                    self.feishu.reply_text(message_id, reply)
                return

            # 普通 RAG 问答：先 ack 立即告知"在查了"，再排队 RAG
            if message_id and self.feishu.client:
                self.feishu.reply_text(message_id, ACK_LOOKUP)

            # 提交 RAG 到单 worker 池
            self._rag_executor.submit(
                self._run_rag_and_reply, text, user_id, message_id
            )

        except Exception as e:
            logger.exception("处理消息异常: %s", e)

    def _run_rag_and_reply(self, text: str, user_id, message_id) -> None:
        """跑在 RAG worker 线程（max_workers=1）。结果通过 FeishuIOWorker 回写。"""
        try:
            answer, _ = self.handler.process_question(
                question=text, user_id=user_id, message_id=message_id
            )
        except Exception as e:
            logger.exception("RAG 失败: %s", e)
            answer = f"❌ 处理失败：{e}"

        if message_id and self.feishu.client:
            self.feishu.reply_text(message_id, answer)

    def _try_handle_command(self, text: str, user_id: str,
                            message_id: str) -> tuple:
        """尝试作为管理命令处理。返回 (handled, reply_text)"""
        if not text:
            return False, ""

        stripped = text.strip()
        cmd = stripped.split()
        if not cmd:
            return False, ""

        head = cmd[0]

        # 1. 反馈列表 / 待处理反馈
        if head in ("反馈列表", "待处理反馈"):
            items = self.feedback.list_feedback(status=STATUS_PENDING, limit=10)
            if not items:
                return True, "✅ 当前没有待处理反馈"
            lines = [f"📋 待处理反馈（{len(items)} 条）："]
            for i, r in enumerate(items, 1):
                q = r.get("用户问题", "")[:40]
                fb_id = r.get("id", "")
                ftype = r.get("反馈类型", "")
                lines.append(f"{i}. `{fb_id}` [{ftype}] {q}...")
            lines.append("\n标记示例：标记 fb-20260603-001 已处理")
            return True, "\n".join(lines)

        # 2. 标记 <id> <status> [note]
        if head == "标记" and len(cmd) >= 3:
            fb_id = cmd[1]
            status = cmd[2]
            note = " ".join(cmd[3:]) if len(cmd) > 3 else None
            ok, msg = self.feedback.mark(fb_id, status, note=note)
            if ok:
                return True, f"✅ {msg}"
            else:
                return True, f"❌ {msg}"

        # 3. 帮助
        if head in ("帮助", "help", "/help"):
            return True, (
                "📖 管理命令：\n"
                "• 反馈列表 — 查看待处理反馈\n"
                "• 标记 <id> <待处理/已处理/已忽略> [备注] — 标记反馈\n"
                "• 帮助 — 显示本帮助\n\n"
                "管理员 open_id 需在 .env 中配置 FEISHU_ADMIN_OPEN_ID"
            )

        return False, ""

    def _on_card_action_trigger(self, data: P2CardActionTrigger) -> dict:
        """处理卡片按钮点击（mark_feedback action）

        返回 dict 给 SDK 渲染 toast/更新卡片
        """
        try:
            event = data.event
            if event is None:
                return {}
            action = getattr(event, "action", None)
            if not action:
                return {}
            value = getattr(action, "value", None) or {}
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    return {}
            action_name = value.get("action")
            if action_name != "mark_feedback":
                return {}
            fb_id = value.get("feedback_id")
            status = value.get("status")
            if not fb_id or not status:
                return {}

            ok, msg = self.feedback.mark(fb_id, status)
            print(f"[卡片回调] {fb_id} → {status}: {msg}")

            response: dict = {
                "toast": {
                    "type": "success" if ok else "error",
                    "content": msg
                }
            }

            # 标记成功后，返回新卡片覆盖原卡片（去掉按钮、显示新状态）
            if ok:
                rec, _ = self.feedback.find_by_id(fb_id)
                if rec:
                    new_card = self._build_updated_card(rec, status)
                    response["card"] = {
                        "type": "raw",
                        "data": new_card
                    }

            return response
        except Exception as e:
            import traceback
            print(f"ERROR: 卡片回调处理异常 {e}")
            traceback.print_exc()
            return {"toast": {"type": "error", "content": f"处理失败：{e}"}}

    def _build_updated_card(self, rec: dict, new_status: str) -> dict:
        """标记后返回的更新卡片（无按钮，显示新状态）"""
        # 按新状态上色：已处理=绿，已忽略=灰
        status_color_map = {
            "已处理": "green",
            "已忽略": "grey",
        }
        header_color = status_color_map.get(new_status, "blue")

        question = rec.get("用户问题", "")
        answer = rec.get("机器人回复", "")
        fb_id = rec.get("id", "")
        ftype = rec.get("反馈类型", "")
        handle_time = rec.get("处理时间", "")
        handle_note = rec.get("处理备注", "")

        max_len = 300
        if len(question) > max_len:
            question = question[:max_len] + "..."
        if len(answer) > max_len:
            answer = answer[:max_len] + "..."

        elements = [
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {
                        "tag": "lark_md",
                        "content": f"**反馈状态**\n<text_tag color=\"{header_color}\">{new_status}</text_tag>"
                    }},
                    {"is_short": True, "text": {
                        "tag": "lark_md",
                        "content": f"**处理时间**\n{handle_time or '-'}"
                    }}
                ]
            },
            {"tag": "hr"},
            {"tag": "div", "text": {
                "tag": "lark_md",
                "content": f"**反馈ID**\n`{fb_id}`（{ftype}）"
            }},
            {"tag": "div", "text": {
                "tag": "lark_md",
                "content": f"**用户问题**\n{question}"
            }},
            {"tag": "div", "text": {
                "tag": "lark_md",
                "content": f"**机器人回复**\n{answer}"
            }},
        ]
        if handle_note:
            elements.append({"tag": "div", "text": {
                "tag": "lark_md",
                "content": f"**处理备注**\n{handle_note}"
            }})
        elements.append({"tag": "note", "elements": [
            {"tag": "plain_text", "content": "FAQ机器人 · 反馈收集"}
        ]})

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "用户反馈通知"},
                "template": header_color
            },
            "elements": elements,
        }

    def _on_chat_entered(self, data: P2ImChatAccessEventBotP2pChatEnteredV1) -> None:
        try:
            print("[用户进入会话]")
        except Exception as e:
            print(f"ERROR: 处理进入会话事件异常 {e}")

    def stop(self):
        self.running = False
        if self.ws_client:
            print("飞书WebSocket已断开")


class FeishuWSRunner:
    def __init__(self):
        self.ws = FeishuWebSocket()
        self.thread = None

    def run(self):
        self.ws.start()
        if self.ws.running:
            self.thread = threading.Thread(target=self._wait, daemon=True)
            self.thread.start()

    def _wait(self):
        while self.ws.running:
            time.sleep(1)

    def stop(self):
        self.ws.stop()
