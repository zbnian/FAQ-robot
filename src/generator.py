"""
Generator - Ollama 生成模块
"""
import requests
from config.settings import settings


SYSTEM_PROMPT = """你是一个咖啡知识助手。根据以下知识库内容回答用户问题。
如果知识库没有相关内容，请回复"暂无此信息"。

知识库内容：
{context}

用户问题：{question}

回答要求：
1. 简洁准确
2. 如有来源请注明
"""


class Generator:
    """Ollama 生成器"""

    def __init__(self):
        self.base_url = settings.ollama_base_url
        self.model = settings.ollama_model

    def generate(self, context: str, question: str) -> str:
        """
        调用 Ollama 生成回答

        Args:
            context: 检索到的上下文
            question: 用户问题

        Returns:
            生成的回答
        """
        if not context or not context.strip():
            return "暂无此信息"

        prompt = SYSTEM_PROMPT.format(context=context, question=question)

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9
                    }
                },
                timeout=120
            )
            response.raise_for_status()
            result = response.json().get("response", "").strip()

            if not result:
                return "暂无此信息"

            return result

        except requests.exceptions.ConnectionError:
            return "无法连接到 Ollama 服务"
        except requests.exceptions.Timeout:
            return "Ollama 服务响应超时"
        except Exception as e:
            return f"生成失败: {str(e)}"


if __name__ == "__main__":
    gen = Generator()
    result = gen.generate(
        context="咖啡是一种饮料，产自咖啡属植物的种子。",
        question="什么是咖啡？"
    )
    print(result)