"""
FAISS Indexer - 按 ## 二级标题分块构建索引

进程内单例：所有 retriever / scheduler / MessageHandler 共享同一份内存索引。
重建期间通过 RLock 拒绝查询，避免 FAISS Index 对象被并发改写。
"""
import re
import threading
from pathlib import Path
from typing import List, Tuple, Optional
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from config.settings import settings


class Chunk:
    """知识库分块"""
    def __init__(self, title: str, content: str, source: str):
        self.title = title
        self.content = content
        self.source = source

    def to_text(self) -> str:
        return f"{self.title}\n{self.content}"


class FAISSIndexer:
    """FAISS 索引构建器"""

    def __init__(self):
        self.model = SentenceTransformer(settings.embedding_model)
        self.chunks: List[Chunk] = []
        self.index: Optional[faiss.Index] = None
        # 读/写锁：scheduler 重建时持写锁（独占），retriever 查询时持读锁（共享）。
        # 重建期间持写锁，未抢到读锁的查询会直接收到"暂无此信息"，避免 FAISS
        # 内部状态在 add() 进行中被 search() 读到崩溃。
        self._rwlock = threading.RLock()
        self._rebuilding = False

    def is_rebuilding(self) -> bool:
        """scheduler 重建期间为 True，retriever 可据此快速放行/拒绝"""
        return self._rebuilding

    def acquire_read(self, timeout: float = 0.0) -> Optional[threading.RLock]:
        """抢读锁。返回 RLock 表示抢到（用 with 释放），返回 None 表示超时/重建中。

        retriever 调用：timeout=0 即非阻塞；scheduler 重建瞬间持写锁，没抢到就
        直接返回空上下文，避免卡住飞书/企微消息回复。
        """
        if self._rebuilding:
            return None
        acquired = self._rwlock.acquire(blocking=False)
        if not acquired:
            return None
        # 抢到锁后再确认一次（防止抢锁过程中 scheduler 进入 rebuilding）
        if self._rebuilding:
            self._rwlock.release()
            return None
        return self._rwlock

    def acquire_write(self) -> threading.RLock:
        """抢写锁（阻塞）。scheduler 重建时调用：设置 _rebuilding 并阻塞所有新读锁。"""
        self._rebuilding = True
        self._rwlock.acquire()
        return self._rwlock

    def release_write(self) -> None:
        """释放写锁并清除重建标记。"""
        self._rebuilding = False
        self._rwlock.release()

    def reload_in_memory(self) -> None:
        """重建完成后，从刚写出的磁盘文件重新 load 到内存。

        scheduler 在 build_index(force=True) 写盘后调用本方法，确保所有持同一
        引用（单例）的 retriever 看到的是新索引。
        """
        with self._rwlock:
            self._rebuilding = True
            try:
                self.load_index()
            finally:
                self._rebuilding = False

    def load_knowledge_base(self, kb_path: Path) -> List[Chunk]:
        """加载知识库，按 ## 二级标题分块"""
        chunks = []
        current_h1 = ""
        current_h2 = ""
        current_content = []

        for md_file in kb_path.rglob("*.md"):
            if md_file.name == "README.md":
                continue

            content = md_file.read_text(encoding="utf-8")
            lines = content.split("\n")

            for line in lines:
                h1_match = re.match(r"^#\s+(.+)$", line)
                h2_match = re.match(r"^##\s+(.+)$", line)

                if h1_match:
                    current_h1 = h1_match.group(1)
                elif h2_match:
                    if current_h2 and current_content:
                        text = "\n".join(current_content).strip()
                        if text:
                            chunks.append(Chunk(
                                f"{current_h1} - {current_h2}",
                                text,
                                md_file.name
                            ))
                    current_h2 = h2_match.group(1)
                    current_content = []
                elif current_h2:
                    current_content.append(line)

            if current_h2 and current_content:
                text = "\n".join(current_content).strip()
                if text:
                    chunks.append(Chunk(
                        f"{current_h1} - {current_h2}",
                        text,
                        md_file.name
                    ))

        return chunks

    def build_index(self, kb_path: Optional[Path] = None, force: bool = False):
        """构建 FAISS 索引"""
        kb_path = kb_path or settings.coffee_path
        index_path = settings.faiss_index_path
        chunks_path = index_path.parent / "chunks.pkl"

        if not force and index_path.exists():
            self.load_index(index_path)
            return

        self.chunks = self.load_knowledge_base(kb_path)
        texts = [chunk.to_text() for chunk in self.chunks]

        vectors = self.model.encode(texts, normalize_embeddings=True)
        vectors = np.array(vectors).astype("float32")

        dim = vectors.shape[1]
        self.index = faiss.IndexFlatIP(dim)
        self.index.add(vectors)

        index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(index_path))

        import pickle
        with open(chunks_path, "wb") as f:
            pickle.dump(self.chunks, f)

    def load_index(self, index_path: Optional[Path] = None):
        """加载 FAISS 索引"""
        index_path = index_path or settings.faiss_index_path
        chunks_path = index_path.parent / "chunks.pkl"
        self.index = faiss.read_index(str(index_path))

        import pickle
        if chunks_path.exists():
            with open(chunks_path, "rb") as f:
                self.chunks = pickle.load(f)
        else:
            self.chunks = []

    def search(self, query: str, top_k: int = 3) -> List[Tuple[Chunk, float]]:
        """搜索最相似的 top_k 个 chunk。

        重建期间返回空列表，retriever 据此走"暂无此信息"分支。
        """
        lock = self.acquire_read()
        if lock is None:
            return []
        try:
            if self.index is None:
                self.load_index()

            query_vec = self.model.encode([query], normalize_embeddings=True)
            query_vec = np.array(query_vec).astype("float32")

            scores, indices = self.index.search(query_vec, top_k * 2)

            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < len(self.chunks) and score >= settings.similarity_threshold:
                    results.append((self.chunks[idx], float(score)))

            return results[:top_k]
        finally:
            lock.release()


_indexer_instance: Optional["FAISSIndexer"] = None
_indexer_lock = threading.Lock()


def get_indexer() -> "FAISSIndexer":
    """进程内单例。所有 retriever / scheduler / MessageHandler 必须用此函数获取。

    锁外面建实例（SentenceTransformer 加载慢），建好之后单例无锁返回。
    """
    global _indexer_instance
    if _indexer_instance is None:
        with _indexer_lock:
            if _indexer_instance is None:
                _indexer_instance = FAISSIndexer()
    return _indexer_instance


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    indexer = get_indexer()
    indexer.build_index(force=args.rebuild)
    print(f"索引构建完成，共 {len(indexer.chunks)} 个chunk")