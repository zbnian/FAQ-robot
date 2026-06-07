"""
通知模块 - 飞书通知发给你
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config.settings import settings


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=2, backoff_factor=0.3, status_forcelist=[502, 503, 504])
    adapter = HTTPAdapter(pool_connections=4, pool_maxsize=4, max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class Notifier:
    """通知器"""

    def __init__(self):
        self.webhook_url = settings.feishu_webhook_url
        self.session = _build_session()

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

            response = self.session.post(
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
