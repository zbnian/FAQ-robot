"""
FAISS Indexer - 按 ## 二级标题分块构建索引
"""
import re
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

    def load_index(self, index_path: Optional[Path] = None):
        """加载 FAISS 索引"""
        index_path = index_path or settings.faiss_index_path
        self.index = faiss.read_index(str(index_path))

    def search(self, query: str, top_k: int = 3) -> List[Tuple[Chunk, float]]:
        """搜索最相似的 top_k 个 chunk"""
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


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    indexer = FAISSIndexer()
    indexer.build_index(force=args.rebuild)
    print(f"索引构建完成，共 {len(indexer.chunks)} 个chunk")