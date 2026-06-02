"""
Retriever - 向量检索模块（支持 query 扩展）
"""
from typing import List, Tuple, Optional, Set
from config.settings import settings
from src.indexer import FAISSIndexer


class RetrievedChunk:
    """检索结果"""
    def __init__(self, text: str, source: str, score: float, query_used: str = ""):
        self.text = text
        self.source = source
        self.score = score
        self.query_used = query_used  # 命中此 chunk 的查询（原始或变体）


class Retriever:
    """向量检索器"""

    def __init__(self, enable_expansion: bool = True, enable_llm_expansion: bool = True,
                 variant_score_decay: float = 0.85):
        self.indexer = FAISSIndexer()
        self._index_loaded = False
        self.enable_expansion = enable_expansion
        self.enable_llm_expansion = enable_llm_expansion
        self.variant_score_decay = variant_score_decay  # 变体得分折扣（避免变体抢走Top1）
        self._expander = None

    def _ensure_index(self):
        """确保索引已加载"""
        if not self._index_loaded:
            self.indexer.load_index()
            self._index_loaded = True

    def _get_expander(self):
        """懒加载 query 扩展器"""
        if self._expander is None and self.enable_expansion:
            from src.auto_optimizer import QueryExpansionLearner
            self._expander = QueryExpansionLearner()
        return self._expander

    def retrieve(self, query: str, top_k: Optional[int] = None) -> List[RetrievedChunk]:
        """
        检索与问题最相关的chunk（单次检索，不做扩展）

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
            RetrievedChunk(text=chunk.to_text(), source=chunk.source, score=score, query_used=query)
            for chunk, score in results
        ]

    def retrieve_with_expansion(self, query: str, top_k: Optional[int] = None,
                                  use_llm: bool = True) -> List[RetrievedChunk]:
        """
        带 query 扩展的检索：原 query + 词典变体 + LLM 变体，合并去重

        Args:
            query: 用户问题
            top_k: 最终返回的 top_k（每个变体也取 top_k 候选）
            use_llm: 是否启用 LLM 改写

        Returns:
            合并去重后的 top_k 结果（按相似度倒序）
        """
        self._ensure_index()
        k = top_k or settings.top_k
        expander = self._get_expander()

        # 收集所有要检索的 query：原 query + 变体
        queries = [query]
        if expander:
            variants = expander.expand(query, use_llm=use_llm and self.enable_llm_expansion)
            queries.extend(variants)

        # 每个 query 检索 top_k，结果合并去重
        # 原始 query 不折扣（decay=1.0），变体 query 乘以 variant_score_decay
        # 用 chunk 在 self.indexer.chunks 中的索引做唯一 key
        best: dict[int, RetrievedChunk] = {}
        for i, q in enumerate(queries):
            decay = 1.0 if i == 0 else self.variant_score_decay
            for chunk, score in self.indexer.search(q, k):
                if not hasattr(chunk, '_idx'):
                    chunk._idx = id(chunk)  # 用 id 作 fallback
                idx = self.indexer.chunks.index(chunk) if chunk in self.indexer.chunks else id(chunk)
                final_score = float(score) * decay
                if idx not in best or best[idx].score < final_score:
                    best[idx] = RetrievedChunk(
                        text=chunk.to_text(),
                        source=chunk.source,
                        score=final_score,
                        query_used=q
                    )

        # 按相似度倒序，取 top_k
        results = sorted(best.values(), key=lambda x: -x.score)[:k]
        return results

    def get_context(self, query: str, top_k: Optional[int] = None) -> str:
        """
        获取拼接的上下文字符串（带 query 扩展）

        Args:
            query: 用户问题
            top_k: 返回数量

        Returns:
            拼接的上下文字符串
        """
        results = self.retrieve_with_expansion(query, top_k)

        if not results:
            return ""

        contexts = []
        for r in results:
            contexts.append(f"【{r.source}】\n{r.text}")

        return "\n\n".join(contexts)