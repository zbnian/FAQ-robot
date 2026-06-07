"""
Generator - Ollama 生成模块

支持流式输出（on_token 回调）+ Session 复用 + 600s timeout。
流式是为了让 SDK 不被同步推理阻塞（设备上 qwen2.5:3b 单推理 180s，
同步等 180s 时 SDK 心跳 / 重连 / 新消息全卡死）。
"""
from typing import Callable, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config.settings import settings

# 推理超时：qwen2.5:3b 设备实测 180s，留 3 倍缓冲
GENERATE_TIMEOUT_SECONDS = 600


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


def _build_session() -> requests.Session:
    """构造带连接池 + 重试的 Session（进程内多 Generator 实例可共用）"""
    session = requests.Session()
    retry = Retry(total=2, backoff_factor=0.3, status_forcelist=[502, 503, 504])
    adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class Generator:
    """Ollama 生成器"""

    def __init__(self):
        self.base_url = settings.ollama_base_url
        self.model = settings.ollama_model
        self.session = _build_session()

    def generate(self, context: str, question: str) -> str:
        """非流式：内部用 streaming 但等流结束返回完整字符串。

        适用于 handler 同步等待答案的场景（如飞书 IO worker）。
        """
        return self._generate(context, question, on_token=None, timeout=GENERATE_TIMEOUT_SECONDS)

    def generate_streaming(self, context: str, question: str,
                           on_token: Callable[[str], None]) -> str:
        """流式：每收到一个 token 调一次 on_token。

        on_token 跑在调用方线程（这里），调用方应负责把 token 跨线程送回
        SDK 的 event loop（如 asyncio.run_coroutine_threadsafe）。

        Returns:
            拼接好的完整答案。
        """
        return self._generate(context, question, on_token=on_token, timeout=GENERATE_TIMEOUT_SECONDS)

    def _generate(self, context: str, question: str,
                  on_token: Optional[Callable[[str], None]], timeout: int) -> str:
        if not context or not context.strip():
            return "暂无此信息"

        prompt = SYSTEM_PROMPT.format(context=context, question=question)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,  # 流式：每行 NDJSON 一个 {"response": "..."} 增量
            "options": {
                "temperature": 0.3,
                "top_p": 0.9
            }
        }

        try:
            response = self.session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                stream=True,
                timeout=timeout,
            )
            response.raise_for_status()

            chunks: list[str] = []
            # iter_lines 是按 \n 切分；Ollama 流式 NDJSON 是一行一个 {"response": "..."}
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                try:
                    import json
                    obj = json.loads(raw_line)
                except (ValueError, TypeError):
                    # 非 JSON 行（极少见），当成纯文本
                    chunks.append(raw_line)
                    continue
                # Ollama 末尾发 {"response":"", "done":true} 收尾
                if obj.get("done") is True:
                    break
                token = obj.get("response", "")
                if token:
                    chunks.append(token)
                    if on_token is not None:
                        try:
                            on_token(token)
                        except Exception:
                            # on_token 抛错不能影响主流程；吞掉
                            pass

            result = "".join(chunks).strip()
            return result or "暂无此信息"

        except requests.exceptions.ConnectionError:
            return "无法连接到 Ollama 服务"
        except requests.exceptions.Timeout:
            return "Ollama 服务响应超时"
        except Exception as e:
            return f"生成失败: {str(e)}"


if __name__ == "__main__":
    gen = Generator()

    def show(tok):
        print(tok, end="", flush=True)

    print("--- streaming ---")
    result = gen.generate_streaming(
        context="咖啡是一种饮料，产自咖啡属植物的种子。",
        question="什么是咖啡？",
        on_token=show,
    )
    print("\n--- result ---")
    print(result)