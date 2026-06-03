"""
通知模块 - 飞书通知发给你
"""
import requests
from config.settings import settings


class Notifier:
    """通知器"""

    def __init__(self):
        self.webhook_url = settings.feishu_webhook_url

    def notify(self, title: str, content: str) -> bool:
        """
        发送飞书通知

        Args:
            title: 通知标题
            content: 通知内容

        Returns:
            是否发送成功
        """
        if not self.webhook_url:
            print("WARN: 飞书webhook未配置，跳过通知")
            return False

        try:
            message = {
                "msg_type": "text",
                "content": {
                    "text": f"{title}\n\n{content}"
                }
            }

            response = requests.post(
                self.webhook_url,
                json=message,
                timeout=10
            )

            if response.status_code == 200:
                return True
            else:
                print(f"ERROR: 通知发送失败 {response.status_code}")
                return False

        except Exception as e:
            print(f"ERROR: 通知发送异常 {e}")
            return False

    def notify_feedback(self, question: str, answer: str, feedback_type: str):
        """通知反馈"""
        content = f"""## 用户反馈
- 时间：刚才
- 用户问题：{question}
- 机器人回复：{answer}
- 反馈类型：{feedback_type}"""
        return self.notify("用户反馈", content)
