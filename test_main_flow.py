import sys
sys.stdout.write("[TEST] Script starting...\n")
sys.stdout.flush()

from config.settings import settings
sys.stdout.write(f"[TEST] settings.wechat_bot_id = {settings.wechat_bot_id}\n")
sys.stdout.flush()

from src.indexer import FAISSIndexer
sys.stdout.write("[TEST] FAISSIndexer imported\n")
sys.stdout.flush()

indexer = FAISSIndexer()
sys.stdout.write("[TEST] FAISSIndexer created, building index...\n")
sys.stdout.flush()
indexer.build_index()
sys.stdout.write("[TEST] Index built\n")
sys.stdout.flush()

from src.wechat_ws import WeComWSRunner
sys.stdout.write("[TEST] WeComWSRunner imported\n")
sys.stdout.flush()

wechat_runner = WeComWSRunner()
sys.stdout.write(f"[TEST] WeComWSRunner created, ws.running = {wechat_runner.ws.running}\n")
sys.stdout.flush()

wechat_runner.run()
sys.stdout.write(f"[TEST] wechat_runner.run() called, ws.running = {wechat_runner.ws.running}\n")
sys.stdout.flush()

sys.stdout.write("[TEST] Waiting 10 seconds...\n")
sys.stdout.flush()
import time
time.sleep(10)

sys.stdout.write("[TEST] Done, stopping...\n")
sys.stdout.flush()
wechat_runner.stop()
sys.stdout.write("[TEST] Stopped\n")
sys.stdout.flush()