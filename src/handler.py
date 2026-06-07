"""
消息处理器
"""
from typing import Callable, Optional, Tuple
from src.generator import Generator
from src.feishu_client import FeishuClient
from src.feedback import FeedbackCollector, get_feedback_collector
from src.retriever import get_retriever

NO_INFO_MARKER = "暂无此信息"


class MessageHandler:
    """消息处理器"""

    def __init__(self):
        self.retriever = get_retriever()
        self.generator = Generator()
        self.feishu = FeishuClient()
        self.feedback = get_feedback_collector()

    def process_question(self, question: str, user_id: Optional[str] = None,
                       message_id: Optional[str] = None) -> Tuple[str, bool]:
        """处理用户问题（同步：返回完整答案）"""
        answer, ok = self._do_process(question)
        return answer, ok

    def process_question_streaming(self, question: str, user_id: Optional[str],
                                    message_id: Optional[str],
                                    on_token: Callable[[str], None]) -> str:
        """处理用户问题（流式：每个 token 调一次 on_token）。

        流式场景：调用方通常在 worker 线程跑本方法，on_token 回调内
        把 token 跨线程送回 SDK 的 event loop（如 asyncio.run_coroutine_threadsafe）。
        """
        return self._do_process(question, on_token=on_token)[0]

    def _do_process(self, question: str,
                    on_token: Optional[Callable[[str], None]] = None) -> Tuple[str, bool]:
        """实际处理逻辑（同步 / 流式共用）

        Returns:
            (answer, ok)
        """
        context = self.retriever.get_context(question)

        if not context:
            if not self._is_rebuilding():
                self.feedback.collect(question, NO_INFO_MARKER, "no_context")
            return NO_INFO_MARKER, False

        if on_token is not None:
            answer = self.generator.generate_streaming(context, question, on_token)
        else:
            answer = self.generator.generate(context, question)

        if self._is_no_info(answer):
            if not self._is_rebuilding():
                self.feedback.collect(question, answer, "no_answer")

        return answer, True

    def _is_rebuilding(self) -> bool:
        """indexer 是否在重建（重建期间不写 feedback）"""
        try:
            return self.retriever.indexer.is_rebuilding()
        except Exception:
            return False

    def _is_no_info(self, answer: str) -> bool:
        """判断 answer 是否本质为"暂无此信息"

        判定规则（任一满足即为真）：
        1. 精确等于"暂无此信息"
        2. 包含"暂无此信息"且前面的内容主要是"未提及/没找到"等否定短语（LLM 包装）
        3. 包含"暂无此信息"且前面紧跟 \n\n 换行（视为 LLM 末尾自我否定）→ 假

        通过这种区分，避免误判 LLM 答了内容后在末尾追加"暂无此信息"的情况。
        """
        if not answer:
            return True
        s = answer.strip()
        if s == NO_INFO_MARKER:
            return True
        if NO_INFO_MARKER not in s:
            return False

        # 找到"暂无此信息"在 answer 中的位置
        idx = s.index(NO_INFO_MARKER)

        # 规则 3：前面紧跟 \n\n 换行（LLM 末尾自我否定）→ 不算
        if idx >= 2 and s[idx-2:idx] == "\n\n":
            return False
        # 前面紧跟 \n 单换行
        if idx >= 1 and s[idx-1] == "\n":
            return False

        # 规则 2：前面是"未提及/没找到/不存在"等否定短语（LLM 包装）
        prefix = s[:idx].strip()
        if any(kw in prefix for kw in ["未在", "未提及", "未找到", "未提供", "没有找到", "没找到", "不存在", "没有相关", "无相关"]):
            return True

        # 规则 1：剩余内容 < 20 字（容纳问题回声包装）
        leftover = prefix.strip(" 。．.，,；;：:\"'""''")
        return len(leftover) < 20

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