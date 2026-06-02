"""
消息处理器
"""
from typing import Optional, Tuple
from src.retriever import Retriever
from src.generator import Generator
from src.feishu_client import FeishuClient
from src.feedback import FeedbackCollector


class MessageHandler:
    """消息处理器"""

    def __init__(self):
        self.retriever = Retriever()
        self.generator = Generator()
        self.feishu = FeishuClient()
        self.feedback = FeedbackCollector()

    def process_question(self, question: str, user_id: Optional[str] = None,
                       message_id: Optional[str] = None) -> Tuple[str, bool]:
        """
        处理用户问题

        Args:
            question: 用户问题
            user_id: 用户ID（用于飞书发送）
            message_id: 消息ID（用于飞书回复）

        Returns:
            (回答内容, 是否成功)
        """
        context = self.retriever.get_context(question)

        if not context:
            answer = "暂无此信息"
            self.feedback.collect(question, answer, "no_context")
            return answer, False

        answer = self.generator.generate(context, question)

        if answer == "暂无此信息":
            self.feedback.collect(question, answer, "no_answer")

        return answer, True

    def process_feishu_message(self, event: dict) -> Optional[str]:
        """
        处理飞书消息事件

        Args:
            event: 飞书事件字典

        Returns:
            回复内容
        """
        message_type = event.get("message_type")
        if message_type != "text":
            return None

        content = event.get("content", {})
        text = content.get("text", "").strip()

        message_id = event.get("message_id")
        sender = event.get("sender", {})
        user_id = sender.get("sender_id", {}).get("open_id")

        if text.startswith("@机器人"):
            text = text.replace("@机器人", "").strip()

        if not text:
            return None

        answer, _ = self.process_question(text, user_id, message_id)
        return answer