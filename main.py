"""
FAQ 机器人 - 主入口
"""
import argparse
import sys
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

from config.settings import settings
from src.indexer import get_indexer
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
    """重建索引（CLI --rebuild 使用，写盘后进程退出）"""
    logger.info("正在重建索引...")
    indexer = get_indexer()
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
    """启动飞书 + 企业微信 WebSocket（按 env 独立开关）"""
    start_health_server()

    # 共享单例 indexer：飞书/企微/scheduler 共用同一份内存索引
    indexer = get_indexer()
    indexer.build_index()

    # 启动索引重建调度器（每日 03:00）
    from src.scheduler import IndexScheduler
    index_scheduler = IndexScheduler(indexer=indexer)
    index_scheduler.start()
    logger.info("索引自动重建调度器已启动（每日 03:00）")

    runners = []
    channels = []
    if settings.feishu_app_id and settings.feishu_app_secret:
        from src.feishu_ws import FeishuWSRunner
        logger.info("启动飞书WebSocket...")
        feishu_runner = FeishuWSRunner()
        # lark-oapi 的 start() 阻塞，必须跑在子线程里
        threading.Thread(target=feishu_runner.run, daemon=True).start()
        runners.append(feishu_runner)
        channels.append("飞书")
    else:
        logger.info("飞书凭证未配置，跳过飞书通道")

    if settings.wecom_bot_id and settings.wecom_secret:
        from src.wecom_ws import WeComWSRunner
        logger.info("启动企业微信WebSocket...")
        wecom_runner = WeComWSRunner()
        wecom_runner.run()  # SDK 自带事件循环 + 子线程
        runners.append(wecom_runner)
        channels.append("企业微信")
    else:
        logger.info("企业微信凭证未配置，跳过企微通道")

    if not runners:
        logger.error("未配置任何通道凭证，至少需要飞书或企微之一")
        sys.exit(1)

    logger.info(f"FAQ 机器人已启动，等待消息...（通道：{' + '.join(channels)}）")

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到退出信号...")
        index_scheduler.stop()
        for r in runners:
            r.stop()
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
