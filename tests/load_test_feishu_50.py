"""
飞书侧 50 并发压测：验证 >MAX_IN_FLIGHT 拒绝路径

不连真飞书，纯 in-process 测：
  - 构造 50 个 mock P2ImMessageReceiveV1 事件（独立 message_id）
  - 用 RecorderFeishuIO 替换真实 IO worker，捕获所有 reply_text 调用
  - Mock handler.process_question 睡 60s（持续占住 RAG 槽位）
  - 调 _on_message_receive 50 次
  - 断言：11 个 ack = "查找中，请稍等..."，39 个 ack = "系统繁忙..."

前提：mock 重依赖（Retriever / Generator），让 FeishuWebSocket 能 host 上构造。
不传 STREAM_PUSH_INTERVAL 等企微侧逻辑。
"""
import sys
import threading
import time
from pathlib import Path

# 把项目根加进 path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# === mock 重依赖（必须在 import feishu_ws 之前） ===
from src import retriever as r_mod
from src import generator as g_mod
from src import feedback as f_mod

class MockRetriever:
    def get_context(self, q): return ""
    def _ensure_index(self): pass
    def _get_expander(self): return None

class MockGenerator:
    def generate(self, *a, **kw): return ("mock answer", True)
    def generate_streaming(self, *a, **kw): pass

class MockFeedback:
    def collect(self, *a, **kw): return "fb-mock"
    def list_feedback(self, *a, **kw): return []
    def mark(self, *a, **kw): return (True, "ok")
    def find_by_id(self, *a, **kw): return (None, "")

r_mod.Retriever = MockRetriever
r_mod.get_retriever = lambda: MockRetriever()
r_mod._indexer_instance = None

g_mod.Generator = MockGenerator
f_mod.FeedbackCollector = MockFeedback
f_mod.get_feedback_collector = lambda: MockFeedback()


# === 替换 FeishuIOWorker 为 recorder（捕获所有 reply_text 提交） ===
class RecorderFeishuIO:
    """记录 submit 调用的 IO worker 替身，不真正执行任务。"""
    def __init__(self):
        self.submissions = []  # [(fn_name, args, kwargs), ...]
        self._lock = threading.Lock()

    def start(self):
        """兼容 FeishuIOWorker 接口；什么都不做。"""
        pass

    def submit(self, fn, *args, **kwargs) -> bool:
        with self._lock:
            self.submissions.append((fn.__name__, args, kwargs))
        return True


# === 构造 FeishuWebSocket，注入 recorder ===
from src import feishu_io as fio_mod
from src import feishu_ws as fw_mod
from src.feishu_client import FeishuClient

mock_io = RecorderFeishuIO()
fio_mod.get_feishu_io = lambda: mock_io
fio_mod.FeishuIOWorker = RecorderFeishuIO  # 防止 import 后再被引用
# 关键：feishu_ws.py 顶部 `from src.feishu_io import get_feishu_io` 已把
# 名字绑进自己的模块命名空间，__init__ 调的是 fw_mod.get_feishu_io。
# 所以两边都打补丁，确保构造 FeishuWebSocket 时注入 mock。
fw_mod.get_feishu_io = lambda: mock_io

# 替换 _run_rag_and_reply 让它睡 60s（持续占住 RAG 槽位模拟真实慢 RAG）
def slow_run(self, text, user_id, message_id):
    time.sleep(60)
fw_mod.FeishuWebSocket._run_rag_and_reply = slow_run


# === mock lark event（P2ImMessageReceiveV1 的简化版） ===
class MockSenderId:
    def __init__(self, open_id):
        self.open_id = open_id

class MockSender:
    def __init__(self, open_id):
        self.sender_id = MockSenderId(open_id)

class MockMessage:
    def __init__(self, message_id, text, chat_id="oc_test_chat"):
        self.message_id = message_id
        self.message_type = "text"
        self.chat_id = chat_id
        self.chat_type = "p2p"
        self.content = '{"text": "%s"}' % text
        self.mentions = None

class MockEvent:
    def __init__(self, message, sender):
        self.message = message
        self.sender = sender

class MockData:
    def __init__(self, event):
        self.event = event


def build_event(msgid: str, text: str) -> MockData:
    msg = MockMessage(msgid, text)
    sender = MockSender(f"ou_test_{msgid}")
    return MockData(MockEvent(msg, sender))


def main():
    print("=" * 70)
    print("飞书侧 50 并发压测")
    print("=" * 70)

    # 构造 ws
    ws = fw_mod.FeishuWebSocket()
    # 确保 feishu.client 是 truthy（_on_message_receive 检查 self.feishu.client）
    # 默认情况下 .env 没凭证，client 是 None
    if ws.feishu.client is None:
        # 给个 truthy 占位
        ws.feishu.client = object()

    # 生成 50 个事件（独立 message_id）
    events = [(f"msg_load_{i:03d}", build_event(f"msg_load_{i:03d}", f"压测问题 #{i+1}")) for i in range(50)]

    print(f"构造 {len(events)} 个 mock 事件")
    from src._rag_pool import MAX_IN_FLIGHT
    print(f"  MAX_IN_FLIGHT = {MAX_IN_FLIGHT}")
    print()

    # 调用 _on_message_receive 50 次
    print("提交 50 个事件到 _on_message_receive...")
    start = time.time()
    for msgid, data in events:
        try:
            ws._on_message_receive(data)
        except Exception as e:
            print(f"  EXC on {msgid}: {e}")
    elapsed_ms = (time.time() - start) * 1000
    print(f"  耗时 {elapsed_ms:.0f}ms（50 个事件串行处理）")
    print()

    # 给 RAG executor + FeishuIOWorker 一点点时间把 submit 跑完
    time.sleep(0.5)

    # === 分析 recorder 捕获的 reply_text ===
    reply_texts = [s for s in mock_io.submissions if s[0] == "_do_reply_text"]
    ack_lookup = [s for s in reply_texts if fw_mod.ACK_LOOKUP in s[1][1]]
    ack_overload = [s for s in reply_texts if fw_mod.ACK_OVERLOAD in s[1][1]]

    print("=== 结果 ===")
    print(f"IO worker submit 总数: {len(mock_io.submissions)}")
    print(f"  reply_text 调用:    {len(reply_texts)}")
    print(f"  ACK '查找中，请稍等...' (ACK_LOOKUP):    {len(ack_lookup)} (期望 11)")
    print(f"  ACK '系统繁忙，请稍后再试...' (ACK_OVERLOAD): {len(ack_overload)} (期望 39)")
    print()

    # 详细列出前 12 个
    print("前 12 个 reply_text 调用：")
    for i, (name, args, _) in enumerate(reply_texts[:12]):
        msg_id, text = args[0], args[1]
        is_overload = fw_mod.ACK_OVERLOAD in text
        tag = "[OVERLOAD] 过载" if is_overload else "[LOOKUP]   查找"
        print(f"  {i+1:2d}. {tag}  msg_id={msg_id!r}")
    print()

    # 断言
    failed = []
    if len(ack_lookup) != 11:
        failed.append(f"ACK_LOOKUP 数应为 11，实为 {len(ack_lookup)}")
    if len(ack_overload) != 39:
        failed.append(f"ACK_OVERLOAD 数应为 39，实为 {len(ack_overload)}")
    if len(reply_texts) != 50:
        failed.append(f"reply_text 总数应为 50，实为 {len(reply_texts)}")

    if failed:
        print("❌ FAIL:")
        for f in failed:
            print(f"  - {f}")
        return 1
    print("✅ PASS：11 + 39 = 50，拒绝路径生效")
    print()
    print("    第 1-11 条：拿到「查找中，请稍等...」ack → 进 RAG 池排队")
    print("    第 12-50 条：直接拿到「系统繁忙，请稍后再试...」ack → 不排队")
    return 0


if __name__ == "__main__":
    rc = main()
    # 关闭 RAG executor，避免 slow_run 的 sleep(60) 让进程不退出
    from src._rag_pool import shutdown_rag_executor
    shutdown_rag_executor(wait=False)
    sys.exit(rc)
