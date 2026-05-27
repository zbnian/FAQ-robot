"""
Retriever 模块测试
"""
import pytest
from pathlib import Path
import tempfile
import shutil
from src.indexer import FAISSIndexer
from src.retriever import Retriever


class TestRetriever:
    """Retriever 测试"""

    def setup_method(self):
        """创建临时索引"""
        self.temp_dir = tempfile.mkdtemp()
        self.kb_path = Path(self.temp_dir)

        (self.kb_path / "coffee.md").write_text("""# 咖啡知识

## 耶加雪菲
埃塞俄比亚经典产区，花香果香明显。

## 瑰夏
咖啡界的香槟，产自巴拿马。
""", encoding="utf-8")

        indexer = FAISSIndexer()
        indexer.build_index(self.kb_path, force=True)

        self.retriever = Retriever()

    def teardown_method(self):
        """清理临时目录"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_retrieve(self):
        """测试检索"""
        results = self.retriever.retrieve("什么是耶加雪菲", top_k=3)
        assert isinstance(results, list)

    def test_get_context(self):
        """测试获取上下文"""
        context = self.retriever.get_context("耶加雪菲是什么", top_k=2)
        assert isinstance(context, str)