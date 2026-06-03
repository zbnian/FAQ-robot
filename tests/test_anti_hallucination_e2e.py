"""
反幻觉端到端测试（依赖 Ollama + 已构建的 FAISS 索引）

直接运行：
    py tests/test_anti_hallucination_e2e.py

pytest 默认会 skip，避免拖慢单测；带 --run-e2e 才会执行。
"""
import sys
from pathlib import Path

import pytest

# 允许在容器外 / 仓库根目录直接运行
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCENARIOS = [
    ("区块链是什么工作原理？", "no_answer", "LLM 直接返回\"暂无此信息\""),
    ("卢旺达基伍湖的咖啡风味特点？", "no_answer", "LLM 包装\"未在知识库中提及\""),
    ("什么是量子纠缠？", None, "LLM 答了内容（虽然无关，靠 threshold 兜底）"),
    ("咖啡里加牛奶叫什么？", None, "LLM 正常回答"),
    ("哥斯达黎加塔拉珠的海拔是多少？", None, "LLM 正常回答"),
    ("咖啡对健康有什么影响？", "no_answer", "召回了一些内容但 LLM 没答出来"),
]


def _ollama_ready() -> bool:
    try:
        import requests

        from config.settings import settings
        r = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_ready(), reason="Ollama 未就绪，跳过 E2E")
def test_anti_hallucination_scenarios():
    """所有场景的实际类型 == 期望类型"""
    from src.handler import MessageHandler
    handler = MessageHandler()
    failures = []
    for q, expected_type, note in SCENARIOS:
        ans, _ = handler.process_question(q)
        actual_type = "no_answer" if handler._is_no_info(ans) else None
        if actual_type != expected_type:
            failures.append(f"Q={q!r} expected={expected_type} actual={actual_type} note={note}")
    assert not failures, "反幻觉用例失败：\n" + "\n".join(failures)


def _run_as_script():
    """脚本模式：打印每个场景的回答（用于手动调参）"""
    from src.handler import MessageHandler
    handler = MessageHandler()
    pass_cnt = 0
    for q, expected_type, note in SCENARIOS:
        ans, _ = handler.process_question(q)
        actual_type = "no_answer" if handler._is_no_info(ans) else None
        mark = "✓" if actual_type == expected_type else "✗"
        if actual_type == expected_type:
            pass_cnt += 1
        print(f"{mark} Q: {q}")
        print(f"   期望: {expected_type}, 实际: {actual_type}")
        print(f"   说明: {note}")
        print(f"   A (前80): {ans[:80]!r}\n")
    print(f"通过: {pass_cnt}/{len(SCENARIOS)}")


if __name__ == "__main__":
    _run_as_script()
