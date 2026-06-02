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
        """通知反馈（简单 markdown）"""
        content = f"""## 用户反馈
- 时间：刚才
- 用户问题：{question}
- 机器人回复：{answer}
- 反馈类型：{feedback_type}"""
        return self.notify("用户反馈", content)

    def notify_feedback_detailed(self, question: str, answer: str,
                                 feedback_type: str, timestamp: str):
        """通知反馈（富文本卡片，按类型上色）"""
        if not self.webhook_url:
            print("WARN: 飞书webhook未配置，跳过通知")
            return False

        # 按反馈类型配置标签颜色（红=wrong, 橙=no_answer, 黄=no_context）
        color_map = {
            "wrong": "red",
            "no_answer": "orange",
            "no_context": "yellow",
        }
        tag_color = color_map.get(feedback_type, "blue")
        tag_text = {
            "wrong": "回答有误",
            "no_answer": "无法回答",
            "no_context": "无相关上下文",
        }.get(feedback_type, feedback_type)

        # 截断超长内容（卡片有长度限制）
        max_len = 300
        if len(question) > max_len:
            question = question[:max_len] + "..."
        if len(answer) > max_len:
            answer = answer[:max_len] + "..."

        type_md = (
            "**反馈类型**\n"
            f"<text_tag color=\"{tag_color}\">{tag_text}</text_tag>"
        )

        card = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "用户反馈通知"
                    },
                    "template": tag_color
                },
                "elements": [
                    {
                        "tag": "div",
                        "fields": [
                            {
                                "is_short": True,
                                "text": {
                                    "tag": "lark_md",
                                    "content": type_md
                                }
                            },
                            {
                                "is_short": True,
                                "text": {
                                    "tag": "lark_md",
                                    "content": f"**时间**\n{timestamp}"
                                }
                            }
                        ]
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**用户问题**\n{question}"
                        }
                    },
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**机器人回复**\n{answer}"
                        }
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": "FAQ机器人 · 反馈收集"
                            }
                        ]
                    }
                ]
            }
        }

        try:
            response = requests.post(
                self.webhook_url,
                json=card,
                timeout=10
            )
            if response.status_code == 200:
                return True
            else:
                print(f"ERROR: 反馈卡片发送失败 {response.status_code} {response.text}")
                return False
        except Exception as e:
            print(f"ERROR: 反馈卡片发送异常 {e}")
            return False