from config.settings import settings
from src.wechat_ws import WeComWSRunner
print("Creating runner...")
runner = WeComWSRunner()
print("ws.bot_id:", runner.ws.bot_id)
print("ws.secret len:", len(runner.ws.secret))
print("ws.running:", runner.ws.running)
print("Calling run()...")
runner.run()
print("ws.running after run:", runner.ws.running)
print("Done")