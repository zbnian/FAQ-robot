"""
FAQ 机器人 - 命令行入口
"""
import argparse
import sys
from pathlib import Path

from config.settings import settings
from src.indexer import FAISSIndexer
from src.retriever import Retriever
from src.generator import Generator


def rebuild_index():
    """重建索引"""
    print("正在重建索引...")
    indexer = FAISSIndexer()
    indexer.build_index(force=True)
    print(f"索引构建完成，共 {len(indexer.chunks)} 个 chunk")


def query(question: str):
    """问答"""
    retriever = Retriever()
    generator = Generator()

    print(f"问题: {question}")

    context = retriever.get_context(question)

    if not context:
        print("回答: 暂无此信息")
        return

    answer = generator.generate(context, question)
    print(f"回答: {answer}")


def main():
    parser = argparse.ArgumentParser(description="FAQ 机器人")
    parser.add_argument("--rebuild", action="store_true", help="重建索引")
    parser.add_argument("question", nargs="?", help="用户问题")

    args = parser.parse_args()

    if args.rebuild:
        rebuild_index()
    elif args.question:
        query(args.question)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()