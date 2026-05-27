"""
Generator 模块测试
"""
import pytest
from src.generator import Generator


class TestGenerator:
    """Generator 测试"""

    def setup_method(self):
        self.generator = Generator()

    def test_generate_with_context(self):
        """有上下文时应返回生成结果"""
        result = self.generator.generate(
            context="咖啡是一种饮料。",
            question="什么是咖啡？"
        )
        assert result != "暂无此信息"
        assert len(result) > 0

    def test_generate_without_context(self):
        """无上下文时应返回暂无此信息"""
        result = self.generator.generate("", "什么是咖啡？")
        assert result == "暂无此信息"

    def test_generate_with_empty_context(self):
        """空上下文时应返回暂无此信息"""
        result = self.generator.generate("   ", "什么是咖啡？")
        assert result == "暂无此信息"