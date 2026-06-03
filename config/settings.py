from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # 知识库路径
    coffee_path: Path = Path("/app/coffee")

    # FAISS 索引路径
    faiss_index_path: Path = Path("/app/data/faiss_index.bin")

    # Ollama 配置
    ollama_base_url: str = "http://192.168.31.147:56789"
    ollama_model: str = "qwen2.5:3b-instruct"

    # RAG 参数
    top_k: int = 3
    similarity_threshold: float = 0.6
    embedding_model: str = "moka-ai/m3e-base"

    # 飞书配置
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_webhook_url: str = ""
    # 反馈通知接收方（优先用 open_id，回退到 chat_id，最后 webhook 兜底）
    feishu_admin_open_id: str = ""
    feishu_admin_chat_id: str = ""

    # 日志配置
    log_dir: Path = Path("/app/logs")
    log_retention_days: int = 7

    # 反馈与扩展词库
    feedback_dir: Path = Path("/app/feedbacks")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()