"""
反馈收集模块
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional


class FeedbackCollector:
    """反馈收集器"""

    def __init__(self, feedback_dir: Optional[Path] = None):
        self.feedback_dir = feedback_dir or Path("./feedbacks")
        self.feedback_dir.mkdir(parents=True, exist_ok=True)

    def collect(self, question: str, answer: str, feedback_type: str):
        """
        收集反馈

        Args:
            question: 用户问题
            answer: 机器人回复
            feedback_type: 反馈类型
                - no_context: 无法回答（无相关上下文）
                - no_answer: 返回暂无此信息
                - wrong: 回答有误
        """
        feedback = {
            "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "用户问题": question,
            "机器人回复": answer,
            "反馈类型": feedback_type
        }

        filename = self.feedback_dir / f"feedback_{datetime.now().strftime('%Y%m%d')}.jsonl"

        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(feedback, ensure_ascii=False) + "\n")

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