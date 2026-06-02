"""
反馈收集模块
"""
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional


class FeedbackCollector:
    """反馈收集器（写入文件 + 飞书 webhook 通知）"""

    def __init__(self, feedback_dir: Optional[Path] = None, notifier=None):
        self.feedback_dir = feedback_dir or Path("./feedbacks")
        self.feedback_dir.mkdir(parents=True, exist_ok=True)
        # notifier 懒加载（避免循环 import）
        self._notifier = notifier
        self._notifier_lock = threading.Lock()
        self._notifier_loaded = notifier is not None

    def _get_notifier(self):
        """懒加载 Notifier（避免循环 import）"""
        if not self._notifier_loaded:
            with self._notifier_lock:
                if not self._notifier_loaded:
                    from src.notifier import Notifier
                    self._notifier = Notifier()
                    self._notifier_loaded = True
        return self._notifier

    def collect(self, question: str, answer: str, feedback_type: str,
                notify: bool = True):
        """
        收集反馈

        Args:
            question: 用户问题
            answer: 机器人回复
            feedback_type: 反馈类型
                - no_context: 无法回答（无相关上下文）
                - no_answer: 返回暂无此信息
                - wrong: 回答有误
            notify: 是否同时发送到飞书 webhook
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        feedback = {
            "时间": timestamp,
            "用户问题": question,
            "机器人回复": answer,
            "反馈类型": feedback_type
        }

        filename = self.feedback_dir / f"feedback_{datetime.now().strftime('%Y%m%d')}.jsonl"

        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(feedback, ensure_ascii=False) + "\n")

        # 异步发送到飞书 webhook（不阻塞主流程）
        if notify:
            threading.Thread(
                target=self._send_notify,
                args=(question, answer, feedback_type, timestamp),
                daemon=True
            ).start()

    def _send_notify(self, question: str, answer: str, feedback_type: str, timestamp: str):
        """异步发送飞书通知"""
        try:
            notifier = self._get_notifier()
            # 用富文本卡片展示，更醒目
            notifier.notify_feedback_detailed(
                question=question,
                answer=answer,
                feedback_type=feedback_type,
                timestamp=timestamp
            )
        except Exception as e:
            print(f"WARN: 反馈通知发送失败 {e}")

    def get_recent_feedback(self, limit: int = 10):
        """获取最近反馈"""
        feedbacks = []
        for file in sorted(self.feedback_dir.glob("feedback_*.jsonl"), reverse=True)[:1]:
            with open(file, encoding="utf-8") as f:
                for line in f:
                    feedbacks.append(json.loads(line.strip()))
                    if len(feedbacks) >= limit:
                        break
        return feedbacks