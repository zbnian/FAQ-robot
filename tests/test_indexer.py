"""
Indexer 模块测试
"""
import pytest
from pathlib import Path
import tempfile
import shutil
from src.indexer import FAISSIndexer, Chunk


class TestFAISSIndexer:
    """FAISSIndexer 测试"""

    def setup_method(self):
        """创建临时知识库"""
        self.temp_dir = tempfile.mkdtemp()
        self.kb_path = Path(self.temp_dir)

        (self.kb_path / "test1.md").write_text("""# 咖啡知识

## 什么是咖啡
咖啡是一种饮料，由咖啡豆制成。

## 咖啡产地
咖啡主要产自埃塞俄比亚、巴西等国家。
""", encoding="utf-8")

        (self.kb_path / "test2.md").write_text("""# 烘焙知识

## 浅烘焙
浅烘焙保留原始风味，酸度较高。

## 深烘焙
深烘焙焦苦味重，适合做意式浓缩。
""", encoding="utf-8")

        self.indexer = FAISSIndexer()

    def teardown_method(self):
        """清理临时目录"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_knowledge_base(self):
        """测试加载知识库"""
        chunks = self.indexer.load_knowledge_base(self.kb_path)
        assert len(chunks) >= 4
        assert any("什么是咖啡" in c.title for c in chunks)

    def test_build_index(self):
        """测试构建索引"""
        self.indexer.build_index(self.kb_path, force=True)
        assert self.indexer.index is not None
        assert self.indexer.index.ntotal > 0

    def test_search(self):
        """测试搜索"""
        self.indexer.build_index(self.kb_path, force=True)
        results = self.indexer.search("咖啡是什么", top_k=2)
        assert len(results) > 0
        assert results[0][1] >= 0

    def test_chunk_to_text(self):
        """测试chunk文本转换"""
        chunk = Chunk("标题", "内容", "test.md")
        text = chunk.to_text()
        assert "标题" in text
        assert "内容" in text