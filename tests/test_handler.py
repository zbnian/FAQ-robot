"""
Handler 模块测试
"""
import pytest
from src.handler import MessageHandler


class TestMessageHandler:
    """MessageHandler 测试"""

    def setup_method(self):
        self.handler = MessageHandler()

    def test_handler_init(self):
        """测试处理器初始化"""
        assert self.handler is not None
        assert self.handler.retriever is not None
        assert self.handler.generator is not None


class TestIsNoInfo:
    """_is_no_info 判定规则单元测试（纯逻辑，无外部依赖）"""

    def setup_method(self):
        self.handler = MessageHandler()

    @pytest.mark.parametrize("answer,expected", [
        # 精确等于 / 末尾标点
        ("暂无此信息", True),
        ("暂无此信息。", True),
        # 否定短语包装
        ("卢旺达基伍湖的咖啡风味特点未在知识库中提及，因此答案为：暂无此信息。", True),
        # 短包装（剩余 < 20 字）
        ("卢旺达基伍湖地区的咖啡风味特点暂无此信息。", True),
        # 末尾自我否定（LLM 答完内容后追加，不算）
        ("量子纠缠是一种在量子物理学中发现的现象。\n\n来源：维基百科\n\n暂无此信息", False),
        ("回答：在咖啡中加入牛奶的做法被称为卡布奇诺。\n\n来源：暂无此信息", False),
        # 正常答案
        ("哥斯达黎加塔拉珠的海拔是1500-1950米。", False),
        # 空字符串
        ("", True),
    ])
    def test_is_no_info(self, answer, expected):
        assert self.handler._is_no_info(answer) is expected
