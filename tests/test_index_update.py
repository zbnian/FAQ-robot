"""
索引更新测试
"""
import pytest
import tempfile
import shutil
from pathlib import Path
from src.indexer import FAISSIndexer


class TestIndexUpdate:
    """索引更新测试"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.kb_path = Path(self.temp_dir)

        (self.kb_path / "coffee.md").write_text("""# 咖啡

## 测试
测试内容
""", encoding="utf-8")

        self.indexer = FAISSIndexer()
        self.indexer.build_index(self.kb_path, force=True)

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_index_exists(self):
        """测试索引存在"""
        assert self.indexer.index is not None
        assert self.indexer.index.ntotal > 0