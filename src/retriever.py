"""
Retriever - 向量检索模块（支持 query 扩展）

共享单例 indexer：与 scheduler / 飞书 / 企微通道共用同一份内存索引，scheduler
重建后无需重启进程即生效。
"""
import threading
from typing import List, Tuple, Optional, Set
from config.settings import settings
from src.indexer import FAISSIndexer, get_indexer


class RetrievedChunk:
    """检索结果"""
    def __init__(self, text: str, source: str, score: float, query_used: str = ""):
        self.text = text
        self.source = source
        self.score = score
        self.query_used = query_used  # 命中此 chunk 的查询（原始或变体）


# 进程内单例：飞书 / 企微 runner 走同一份 retriever，expander 也只初始化一次
_retriever_instance: Optional["Retriever"] = None
_retriever_lock = threading.Lock()


def get_retriever() -> "Retriever":
    """获取 Retriever 进程内单例（双重检查锁）"""
    global _retriever_instance
    if _retriever_instance is None:
        with _retriever_lock:
            if _retriever_instance is None:
                _retriever_instance = Retriever()
    return _retriever_instance


class Retriever:
    """向量检索器"""

    def __init__(self, enable_expansion: bool = True, enable_llm_expansion: bool = False,
                 variant_score_decay: float = 0.85, indexer: Optional[FAISSIndexer] = None):
        # 共享单例：传 None 时走 get_indexer()，与 scheduler 持同一份内存索引。
        # 唯一需要新建实例的场景是单测（注入 mock indexer）。
        self.indexer = indexer if indexer is not None else get_indexer()
        self._index_loaded = False
        self._index_lock = threading.Lock()  # 守护 _ensure_index 的 check-then-act
        self.enable_expansion = enable_expansion
        self.enable_llm_expansion = enable_llm_expansion
        self.variant_score_decay = variant_score_decay  # 变体得分折扣（避免变体抢走Top1）
        self._expander = None
        self._expander_lock = threading.Lock()  # 守护 _get_expander 的 check-then-act

    def _ensure_index(self):
        """确保索引已加载（首次查询时懒加载）。并发首次只 load 一次。"""
        if not self._index_loaded:
            with self._index_lock:
                if not self._index_loaded:
                    self.indexer.load_index()
                    self._index_loaded = True

    def _get_expander(self):
        """懒加载 query 扩展器。并发首次只 new 一次。"""
        if self._expander is None and self.enable_expansion:
            with self._expander_lock:
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
        # 用 chunk._idx（在 indexer.load_knowledge_base 时预分配）做唯一 key，
        # O(1) 直接用，免去原来的 O(n) self.indexer.chunks.index(chunk)
        best: dict[int, RetrievedChunk] = {}
        for i, q in enumerate(queries):
            decay = 1.0 if i == 0 else self.variant_score_decay
            for chunk, score in self.indexer.search(q, k):
                idx = getattr(chunk, "_idx", id(chunk))  # fallback 应对未走 indexer 的 chunk
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