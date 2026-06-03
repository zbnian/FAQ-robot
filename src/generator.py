"""
Generator - Ollama 生成模块
"""
import requests
from config.settings import settings


SYSTEM_PROMPT = """你是一个严格的咖啡知识助手。只能根据下方【知识库内容】回答用户问题，禁止使用你自己的知识。

【严格规则】
1. 只能引用【知识库内容】中明确出现的文字；不得改写、补充、推测
2. 如果【知识库内容】不能直接回答问题（包括完全不相关、只有间接提及、只有 wiki 链接页），必须回复"暂无此信息"，不要试图拼凑
3. 不得编造品种、海拔、风味、产地、价格、日期、人物等任何具体事实
4. 回答尽量引用原文表述，简洁直接
5. 如果【知识库内容】为空或只是目录/链接列表，直接回复"暂无此信息"

【知识库内容】
{context}

【用户问题】
{question}

【回答】
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
                        "temperature": 0.3,
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