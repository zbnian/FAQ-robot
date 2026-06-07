"""
Generator 流式 + Session 复用 + timeout 测试

回归目标：
1. generate() / generate_streaming() 走同一 session（连接池复用）
2. streaming 模式下每个 token 调一次 on_token
3. 流末尾的 {"done": true} 不被当作 token
4. on_token 抛错不能影响主流程
5. timeout 600s（不是 120s）
"""
import json
from unittest.mock import MagicMock, patch

from src.generator import Generator, GENERATE_TIMEOUT_SECONDS


def _make_mock_response(lines):
    """构造一个 mock response 对象，iter_lines 返回 lines"""
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.iter_lines = MagicMock(return_value=iter(lines))
    return mock


def _ndjson(token, done=False):
    """构造 Ollama 流式 NDJSON 字符串"""
    obj = {"response": token, "done": done}
    return json.dumps(obj, ensure_ascii=False)


class TestStreamingTokens:
    def setup_method(self):
        self.gen = Generator()
        self.tokens_received = []

    def teardown_method(self):
        self.gen.session.close()

    def test_streaming_invokes_on_token_for_each_chunk(self):
        """3 个 token + 1 个 done 收尾，断言 on_token 收到 3 次"""
        mock_resp = _make_mock_response([
            _ndjson("你好"),
            _ndjson("，"),
            _ndjson("世界"),
            _ndjson("", done=True),
        ])

        with patch.object(self.gen.session, "post", return_value=mock_resp) as mock_post:
            result = self.gen.generate_streaming(
                context="x", question="y",
                on_token=lambda t: self.tokens_received.append(t),
            )

        assert result == "你好，世界"
        assert self.tokens_received == ["你好", "，", "世界"]
        # 验证 stream=True 传了
        kwargs = mock_post.call_args.kwargs
        assert kwargs["stream"] is True

    def test_streaming_does_not_call_on_token_for_done(self):
        """Ollama 末尾行 {"response": "", "done": true} 收尾，不应触发 on_token"""
        mock_resp = _make_mock_response([
            _ndjson("答案"),
            _ndjson("", done=True),
        ])

        with patch.object(self.gen.session, "post", return_value=mock_resp):
            result = self.gen.generate_streaming(
                context="x", question="y",
                on_token=lambda t: self.tokens_received.append(t),
            )

        assert result == "答案"
        # done 行的 response="" 不应触发 on_token；只调 1 次（"答案"）
        assert self.tokens_received == ["答案"]

    def test_on_token_exception_does_not_break_stream(self):
        """on_token 抛错不能中断主流程，后续 token 仍继续"""
        mock_resp = _make_mock_response([
            _ndjson("a"),
            _ndjson("b"),
            _ndjson("c"),
        ])
        call_count = 0

        def bad_on_token(t):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated SDK error")

        with patch.object(self.gen.session, "post", return_value=mock_resp):
            result = self.gen.generate_streaming(
                context="x", question="y", on_token=bad_on_token,
            )

        # 3 个 token 都尝试调过 on_token（即使第 1 个就抛）
        assert call_count == 3
        assert result == "abc"  # 主结果完整

    def test_generate_non_streaming_returns_full_string(self):
        """generate() 不传 on_token，内部仍用 streaming 实现但等流结束"""
        mock_resp = _make_mock_response([
            _ndjson("完整"),
            _ndjson("答案"),
            _ndjson("", done=True),
        ])

        with patch.object(self.gen.session, "post", return_value=mock_resp) as mock_post:
            result = self.gen.generate(context="x", question="y")

        assert result == "完整答案"
        kwargs = mock_post.call_args.kwargs
        assert kwargs["stream"] is True  # 内部走流式


class TestSessionReuse:
    def test_session_is_persistent(self):
        """同一 Generator 实例多次 generate 复用同一 session"""
        gen = Generator()
        gen.session.close()  # cleanup
        gen2 = Generator()
        gen2.session.close()
        # 不同实例可以共享 session 池（连接复用由 HTTPAdapter 管）
        assert gen.session is not gen2.session  # 不同实例独立 session
        # 但同一实例多次调用应一致
        gen3 = Generator()
        s1 = gen3.session
        s2 = gen3.session
        assert s1 is s2
        gen3.session.close()

    def test_timeout_is_600s(self):
        """timeout 必须是 600s（不是 120s），给 qwen2.5:3b 推理留 3 倍缓冲"""
        assert GENERATE_TIMEOUT_SECONDS == 600
        mock_resp = _make_mock_response([_ndjson("x")])
        gen = Generator()
        try:
            with patch.object(gen.session, "post", return_value=mock_resp) as mock_post:
                gen.generate(context="x", question="y")
            kwargs = mock_post.call_args.kwargs
            assert kwargs["timeout"] == 600
        finally:
            gen.session.close()


class TestEmptyContext:
    def test_empty_context_short_circuits(self):
        """空 context 不应发 HTTP 请求，直接返回「暂无此信息」"""
        gen = Generator()
        try:
            with patch.object(gen.session, "post") as mock_post:
                result = gen.generate(context="", question="x")
            assert result == "暂无此信息"
            mock_post.assert_not_called()
        finally:
            gen.session.close()

    def test_whitespace_context_short_circuits(self):
        gen = Generator()
        try:
            with patch.object(gen.session, "post") as mock_post:
                result = gen.generate(context="   \n  ", question="x")
            assert result == "暂无此信息"
            mock_post.assert_not_called()
        finally:
            gen.session.close()
