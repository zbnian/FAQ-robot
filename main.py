"""
FAQ 机器人 - 主入口
"""
import argparse
import sys
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

from config.settings import settings
from src.indexer import FAISSIndexer
from src.retriever import Retriever
from src.generator import Generator
from src.logger import logger


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'ok')
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args):
        pass


def start_health_server():
    server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    logger.info("健康检查服务已启动: 8080")


def rebuild_index():
    """重建索引"""
    logger.info("正在重建索引...")
    indexer = FAISSIndexer()
    indexer.build_index(force=True)
    logger.info(f"索引构建完成，共 {len(indexer.chunks)} 个 chunk")


def query(question: str):
    """问答"""
    retriever = Retriever()
    generator = Generator()

    logger.info(f"问题: {question}")

    context = retriever.get_context(question)

    if not context:
        answer = "暂无此信息"
        print(f"回答: {answer}")
        return answer

    answer = generator.generate(context, question)
    print(f"回答: {answer}")
    return answer


def start_websocket():
    """启动飞书WebSocket"""
    from src.feishu_ws import FeishuWSRunner

    start_health_server()
    logger.info("启动飞书WebSocket...")

    indexer = FAISSIndexer()
    indexer.build_index()

    ws_runner = FeishuWSRunner()
    ws_runner.run()

    logger.info("FAQ 机器人已启动，等待飞书消息...")

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到退出信号...")
        ws_runner.stop()
        logger.info("已退出")


def main():
    parser = argparse.ArgumentParser(description="FAQ 机器人")
    parser.add_argument("--rebuild", action="store_true", help="重建索引")
    parser.add_argument("--ws", action="store_true", help="启动WebSocket模式")
    parser.add_argument("question", nargs="?", help="用户问题")

    args = parser.parse_args()

    if args.rebuild:
        rebuild_index()
    elif args.ws:
        start_websocket()
    elif args.question:
        query(args.question)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
