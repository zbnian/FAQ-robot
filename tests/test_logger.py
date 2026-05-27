"""
Logger 模块测试
"""
import pytest
import tempfile
import shutil
from pathlib import Path
from src.logger import setup_logger


class TestLogger:
    """Logger 测试"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_setup_logger(self):
        """测试日志设置"""
        logger = setup_logger("test")
        assert logger is not None
        assert len(logger.handlers) > 0