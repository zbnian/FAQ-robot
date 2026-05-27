"""
调度器 - APScheduler定时任务
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from config.settings import settings
from src.indexer import FAISSIndexer


class IndexScheduler:
    """索引调度器"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.indexer = FAISSIndexer()

    def rebuild_index_job(self):
        """重建索引任务"""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始重建索引...")
        try:
            self.indexer.build_index(force=True)
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 索引重建完成")
        except Exception as e:
            print(f"ERROR: 索引重建失败 {e}")

    def start(self):
        """启动调度器"""
        self.scheduler.add_job(
            self.rebuild_index_job,
            CronTrigger(hour=3, minute=0),
            id="daily_rebuild",
            name="每天凌晨3点重建索引",
            replace_existing=True
        )

        self.scheduler.start()
        print("调度器已启动")

    def stop(self):
        """停止调度器"""
        self.scheduler.shutdown()
        print("调度器已停止")


if __name__ == "__main__":
    scheduler = IndexScheduler()
    scheduler.start()
    print("调度器运行中，按Ctrl+C退出")
    try:
        import time
        time.sleep(60)
    except KeyboardInterrupt:
        scheduler.stop()