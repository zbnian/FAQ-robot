"""
调度器 - APScheduler定时任务
"""
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from config.settings import settings
from src.indexer import FAISSIndexer, get_indexer


class IndexScheduler:
    """索引调度器

    共享单例 indexer：重建时持写锁（acquire_write），期间所有 retriever 查询
    会快速返回空；写盘完成后调用 reload_in_memory() 把新索引 load 到内存，
    飞书/企微通道**当次重启前**即可命中新增/修改的知识库内容。
    """

    def __init__(self, indexer: FAISSIndexer = None):
        self.scheduler = BackgroundScheduler()
        self.indexer = indexer if indexer is not None else get_indexer()

    def rebuild_index_job(self):
        """重建索引任务。持写锁期间 retriever 会快速放行（返回空），不阻塞。"""
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{ts}] 开始重建索引...")
        try:
            write_lock = self.indexer.acquire_write()
            try:
                self.indexer.build_index(force=True)
                # build_index 内部会调用 load_index 重置 self.index / self.chunks
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 索引重建完成，共 {len(self.indexer.chunks)} 个 chunk")
            finally:
                self.indexer.release_write()
        except Exception as e:
            print(f"ERROR: 索引重建失败 {e}")
            import traceback
            traceback.print_exc()

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
        print("调度器已启动（每日 03:00 重建索引）")

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