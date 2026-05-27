"""
Retriever - 向量检索模块
"""
from typing import List, Tuple, Optional
from config.settings import settings
from src.indexer import FAISSIndexer


class RetrievedChunk:
    """检索结果"""
    def __init__(self, text: str, source: str, score: float):
        self.text = text
        self.source = source
        self.score = score


class Retriever:
    """向量检索器"""

    def __init__(self):
        self.indexer = FAISSIndexer()
        self._index_loaded = False

    def _ensure_index(self):
        """确保索引已加载"""
        if not self._index_loaded:
            self.indexer.load_index()
            self._index_loaded = True

    def retrieve(self, query: str, top_k: Optional[int] = None) -> List[RetrievedChunk]:
        """
        检索与问题最相关的chunk

        Args:
            query: 用户问题
            top_k: 返回数量，默认使用配置值

        Returns:
            检索结果列表
        """
        self._ensure_index()

        k = top_k or settings.top_k
        results = self.indexer.search(query, k)

        return [
            RetrievedChunk(text=chunk.to_text(), source=chunk.source, score=score)
            for chunk, score in results
        ]

    def get_context(self, query: str, top_k: Optional[int] = None) -> str:
        """
        获取拼接的上下文字符串

        Args:
            query: 用户问题
            top_k: 返回数量

        Returns:
            拼接的上下文字符串
        """
        results = self.retrieve(query, top_k)

        if not results:
            return ""

        contexts = []
        for r in results:
            contexts.append(f"【{r.source}】\n{r.text}")

        return "\n\n".join(contexts)