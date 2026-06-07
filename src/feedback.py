"""
反馈收集模块（带处理状态 + WebSocket 卡片 + webhook 兜底）

进程内单例：所有通道（飞书 / 企微 / 定时任务）共享同一个 FeedbackCollector，
保证 _seq_lock 唯一。否则两路线程并发 collect 会撞号。
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple

from config.settings import settings

STATUS_PENDING = "待处理"
STATUS_RESOLVED = "已处理"
STATUS_IGNORED = "已忽略"
VALID_STATUSES = {STATUS_PENDING, STATUS_RESOLVED, STATUS_IGNORED}

# 进程内单例：飞书 + 企微 + 定时任务都走同一个 collector，_seq_lock 互通
_instance: Optional["FeedbackCollector"] = None
_init_lock = threading.Lock()

# 通知用 TPE：替代每次 collect 启 daemon thread，避免无界增长
_notify_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fb-notify")
_notify_dropped_count = 0
_notify_dropped_lock = threading.Lock()


def get_feedback_collector() -> "FeedbackCollector":
    """获取 FeedbackCollector 进程内单例（双重检查锁）"""
    global _instance
    if _instance is None:
        with _init_lock:
            if _instance is None:
                _instance = FeedbackCollector()
    return _instance


def shutdown_feedback_collector(wait: bool = False) -> None:
    """进程退出时关闭通知线程池（在 main.py KeyboardInterrupt 路径调用）"""
    _notify_executor.shutdown(wait=wait, cancel_futures=True)


class FeedbackCollector:
    """反馈收集器"""

    def __init__(self, feedback_dir: Optional[Path] = None):
        # 防御手贱 FeedbackCollector() 双 new（单例外的兜底）
        if hasattr(self, "_initialized"):
            return
        self.feedback_dir = feedback_dir or Path("./feedbacks")
        self.feedback_dir.mkdir(parents=True, exist_ok=True)
        self._seq_lock = threading.Lock()
        self._feishu = None
        self._feishu_lock = threading.Lock()
        self._initialized = True

    def _get_feishu(self):
        if self._feishu is None:
            with self._feishu_lock:
                if self._feishu is None:
                    from src.feishu_client import FeishuClient
                    self._feishu = FeishuClient()
        return self._feishu

    def _today_file(self) -> Path:
        return self.feedback_dir / f"feedback_{datetime.now().strftime('%Y%m%d')}.jsonl"

    def _next_seq(self, today: str) -> int:
        filename = self.feedback_dir / f"feedback_{today}.jsonl"
        max_seq = 0
        if filename.exists():
            with open(filename, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        fid = rec.get("id", "")
                        if fid.startswith(f"fb-{today}-"):
                            try:
                                seq = int(fid.rsplit("-", 1)[1])
                                if seq > max_seq:
                                    max_seq = seq
                            except ValueError:
                                pass
                    except json.JSONDecodeError:
                        continue
        return max_seq + 1

    def collect(self, question: str, answer: str, feedback_type: str,
                notify: bool = True) -> str:
        """收集反馈，返回反馈 ID（fb-YYYYMMDD-NNN）"""
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        today = now.strftime("%Y%m%d")

        with self._seq_lock:
            seq = self._next_seq(today)
            feedback_id = f"fb-{today}-{seq:03d}"
            feedback = {
                "id": feedback_id,
                "时间": timestamp,
                "用户问题": question,
                "机器人回复": answer,
                "反馈类型": feedback_type,
                "处理状态": STATUS_PENDING,
                "处理时间": None,
                "处理备注": None,
            }
            filename = self._today_file()
            with open(filename, "a", encoding="utf-8") as f:
                f.write(json.dumps(feedback, ensure_ascii=False) + "\n")

        if notify:
            global _notify_dropped_count
            try:
                _notify_executor.submit(
                    self._notify, question, answer, feedback_type, timestamp, feedback_id
                )
            except RuntimeError:
                # 进程退出阶段 executor 已 shutdown，丢通知但不影响主流程
                with _notify_dropped_lock:
                    _notify_dropped_count += 1

        return feedback_id

    def _notify(self, question: str, answer: str, feedback_type: str,
                timestamp: str, feedback_id: str):
        """发送反馈通知：WebSocket 卡片（带按钮） → webhook 兜底"""
        # 1. WebSocket 卡片（主通道，按钮可点击标记）
        admin_open_id = settings.feishu_admin_open_id
        admin_chat_id = settings.feishu_admin_chat_id
        if admin_open_id or admin_chat_id:
            try:
                feishu = self._get_feishu()
                if not feishu.client:
                    raise RuntimeError("飞书 client 未初始化（缺 app_id/secret）")
                receive_id = admin_open_id or admin_chat_id
                card = self._build_interactive_card(
                    question, answer, feedback_type, timestamp, feedback_id
                )
                if feishu.send_card(receive_id, card):
                    return
                print("WARN: WebSocket 卡片 send_card 返回 False")
            except Exception as e:
                print(f"WARN: WebSocket 卡片发送失败: {e}")

        # 2. webhook 兜底（无按钮，仅查看）
        webhook_url = settings.feishu_webhook_url
        if webhook_url:
            try:
                self._send_webhook(question, answer, feedback_type, timestamp, feedback_id)
                return
            except Exception as e:
                print(f"WARN: webhook 兜底发送失败: {e}")

        print(f"WARN: 反馈 {feedback_id} 未通知（未配置 admin_open_id/chat_id/webhook）")

    def _send_webhook(self, question: str, answer: str, feedback_type: str,
                      timestamp: str, feedback_id: str):
        """webhook 兜底发送（v1 卡片，无按钮）"""
        webhook_url = settings.feishu_webhook_url
        if not webhook_url:
            return

        color_map = {"wrong": "red", "no_answer": "orange", "no_context": "yellow"}
        tag_text = {"wrong": "回答有误", "no_answer": "无法回答", "no_context": "无相关上下文"}
        tag_color = color_map.get(feedback_type, "blue")
        tag_label = tag_text.get(feedback_type, feedback_type)

        max_len = 300
        if len(question) > max_len:
            question = question[:max_len] + "..."
        if len(answer) > max_len:
            answer = answer[:max_len] + "..."

        type_md = (
            "**反馈类型**\n"
            f"<text_tag color=\"{tag_color}\">{tag_label}</text_tag>"
        )

        card = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": "用户反馈通知"},
                    "template": tag_color
                },
                "elements": [
                    {
                        "tag": "div",
                        "fields": [
                            {"is_short": True, "text": {"tag": "lark_md", "content": type_md}},
                            {"is_short": True, "text": {"tag": "lark_md", "content": f"**时间**\n{timestamp}"}}
                        ]
                    },
                    {"tag": "hr"},
                    {"tag": "div", "text": {"tag": "lark_md", "content": f"**反馈ID**\n`{feedback_id}`"}},
                    {"tag": "div", "text": {"tag": "lark_md", "content": f"**用户问题**\n{question}"}},
                    {"tag": "div", "text": {"tag": "lark_md", "content": f"**机器人回复**\n{answer}"}},
                    {"tag": "note", "elements": [{"tag": "plain_text", "content": "FAQ机器人 · 反馈收集"}]}
                ]
            }
        }

        response = requests.post(webhook_url, json=card, timeout=10)
        if response.status_code != 200:
            print(f"ERROR: webhook 发送失败 {response.status_code} {response.text}")

    def _build_interactive_card(self, question: str, answer: str,
                                feedback_type: str, timestamp: str,
                                feedback_id: str) -> dict:
        """构建带按钮的 v1 卡片（msg_type=interactive，按钮回调走 lark-oapi 事件）"""
        color_map = {"wrong": "red", "no_answer": "orange", "no_context": "yellow"}
        tag_text = {"wrong": "回答有误", "no_answer": "无法回答", "no_context": "无相关上下文"}
        tag_color = color_map.get(feedback_type, "blue")
        tag_label = tag_text.get(feedback_type, feedback_type)

        max_len = 300
        if len(question) > max_len:
            question = question[:max_len] + "..."
        if len(answer) > max_len:
            answer = answer[:max_len] + "..."

        type_md = (
            "**反馈类型**\n"
            f"<text_tag color=\"{tag_color}\">{tag_label}</text_tag>"
        )

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "用户反馈通知"},
                "template": tag_color
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": [
                        {"is_short": True, "text": {"tag": "lark_md", "content": type_md}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**时间**\n{timestamp}"}}
                    ]
                },
                {"tag": "hr"},
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**反馈ID**\n`{feedback_id}`"}},
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**用户问题**\n{question}"}},
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**机器人回复**\n{answer}"}},
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "✓ 已处理"},
                            "type": "primary",
                            "value": {
                                "action": "mark_feedback",
                                "feedback_id": feedback_id,
                                "status": STATUS_RESOLVED
                            }
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "✗ 已忽略"},
                            "type": "danger",
                            "value": {
                                "action": "mark_feedback",
                                "feedback_id": feedback_id,
                                "status": STATUS_IGNORED
                            }
                        }
                    ]
                },
                {"tag": "note", "elements": [{"tag": "plain_text", "content": "FAQ机器人 · 反馈收集"}]}
            ]
        }

    def list_feedback(self, status: Optional[str] = None,
                      limit: int = 20) -> List[Dict]:
        """列出反馈（按时间倒序，可按状态过滤）"""
        results: List[Dict] = []
        files = sorted(self.feedback_dir.glob("feedback_*.jsonl"), reverse=True)
        for file in files:
            with open(file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if status is None or rec.get("处理状态") == status:
                        results.append(rec)
                        if len(results) >= limit:
                            return results
        return results

    def find_by_id(self, feedback_id: str) -> Tuple[Optional[Dict], Optional[Path]]:
        """按 ID 查找反馈"""
        for file in sorted(self.feedback_dir.glob("feedback_*.jsonl"), reverse=True):
            with open(file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("id") == feedback_id:
                        return rec, file
        return None, None

    def mark(self, feedback_id: str, status: str,
             note: Optional[str] = None) -> Tuple[bool, str]:
        """标记反馈状态"""
        if status not in VALID_STATUSES:
            return False, f"无效状态：{status}（应为：{'/'.join(VALID_STATUSES)}）"

        rec, filepath = self.find_by_id(feedback_id)
        if rec is None:
            return False, f"找不到反馈：{feedback_id}"

        if rec.get("处理状态") == status and rec.get("处理备注") == note:
            return True, f"已经是「{status}」，无需重复标记"

        with self._seq_lock:
            lines = []
            replaced = False
            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    raw = line.rstrip("\n")
                    if not raw:
                        lines.append("\n")
                        continue
                    try:
                        cur = json.loads(raw)
                    except json.JSONDecodeError:
                        lines.append(line)
                        continue
                    if cur.get("id") == feedback_id and not replaced:
                        cur["处理状态"] = status
                        cur["处理时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        cur["处理备注"] = note
                        lines.append(json.dumps(cur, ensure_ascii=False) + "\n")
                        replaced = True
                    else:
                        lines.append(line)

            if not replaced:
                return False, f"文件已被并发修改，请重试：{feedback_id}"

            tmp = filepath.with_suffix(".jsonl.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(lines)
            tmp.replace(filepath)
            return True, f"已标记 {feedback_id} 为「{status}」"

    def get_recent_feedback(self, limit: int = 10):
        return self.list_feedback(limit=limit)
