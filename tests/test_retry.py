"""call_with_retry 的失败路径测试 —— 全 mock,不打 API。

为什么失败路径必须 mock 测:真实 API 无法稳定制造 429/500,
用伪造"第一次失败、第二次成功"的客户端来验证重试分支(课 14 第 2 步)。
"""
from unittest.mock import MagicMock

import pytest
from openai import APIConnectionError, APIStatusError

import cpp_sentinel.cli as cli
from cpp_sentinel.cli import call_with_retry
from cpp_sentinel.models import Alert


def _status_error(code: int) -> APIStatusError:
    """伪造一个"服务端返回 code"的异常(如 429/401/500)。"""
    resp = MagicMock(status_code=code)
    return APIStatusError("boom", response=resp, body=None)


def _ok(text: str = "ok") -> MagicMock:
    """伪造一个"成功回话"的 client:第 N 次调用返回内容为 text 的 chat 响应。

    必须显式造出 usage——MagicMock 对未设置的属性会编幽灵值,
    "忠实于真实接口形状" 是 mock 测试基本功。
    """
    msg = MagicMock()
    msg.choices = [MagicMock(message=MagicMock(content=text))]
    msg.usage = MagicMock(prompt_tokens=10, completion_tokens=5)   # 账单字段显式成型
    client = MagicMock()
    client.chat.completions.create.return_value = msg
    return client


def test_retry_on_429_then_success():
    """临时故障(429 限流)→ 第 2 次成功:重试生效,返回 attempts=2 + token 账单。"""
    client = _ok("返回成功")
    client.chat.completions.create.side_effect = [_status_error(429), client.chat.completions.create.return_value]
    text, attempts, usage = call_with_retry(client, [{"role": "user", "content": "hi"}])
    assert attempts == 2
    assert text == "返回成功"
    assert usage["prompt_tokens"] > 0      # usage 是 API 明账,成功一定有


def test_retry_on_5xx_then_success():
    """临时故障(503 服务端抖动)→ 重试成功。"""
    client = _ok("恢复")
    client.chat.completions.create.side_effect = [_status_error(503), client.chat.completions.create.return_value]
    text, attempts, _ = call_with_retry(client, [{"role": "user", "content": "hi"}])
    assert attempts == 2
    assert text == "恢复"


def test_retry_on_connection_error_then_success():
    """网络断开(APIConnectionError,连状态码都没有)→ 重试成功。"""
    client = _ok("连上了")
    client.chat.completions.create.side_effect = [APIConnectionError(request=MagicMock()), client.chat.completions.create.return_value]
    text, attempts, _ = call_with_retry(client, [{"role": "user", "content": "hi"}])
    assert attempts == 2
    assert text == "连上了"


def test_no_retry_on_401():
    """永久失败(401 认证/402 余额)→ 绝不重试:只调用 1 次,直接抛。"""
    client = _ok("不该出现")
    client.chat.completions.create.side_effect = [_status_error(401)]
    with pytest.raises(APIStatusError):
        call_with_retry(client, [{"role": "user", "content": "hi"}], max_tries=2)
    assert client.chat.completions.create.call_count == 1, "401 必须放弃,不许重试"


def test_all_fail_raises_after_max_tries():
    """全是临时故障且 2 次都失败 → 试尽后如实上抛,不吞错误。"""
    client = _ok("不该出现")
    client.chat.completions.create.side_effect = [_status_error(500), _status_error(500)]
    with pytest.raises(APIStatusError):
        call_with_retry(client, [{"role": "user", "content": "hi"}], max_tries=2)
    assert client.chat.completions.create.call_count == 2


def test_judge_one_degrades_to_error(monkeypatch):
    """兜底降级:永久失败/任何意外 → judge_one 不崩,返回 error 标记(报告继续)。"""
    monkeypatch.setattr(cli, "build_context", lambda alert, repo: "")   # 免跑真 AST,快
    client = MagicMock()
    client.chat.completions.create.side_effect = [_status_error(401)]
    r = cli.judge_one(client, Alert(file="x.h", line=1, col=1, severity="warning",
                                    check_name="c", message="m"), "/tmp/nope", {})
    assert r.judgement is None
    assert "APIStatusError" in r.error


def _msg(text: str) -> MagicMock:
    """伪造一次"回话":内容必须是合法 JSON(parse_response 要解析它)。"""
    m = MagicMock()
    m.choices = [MagicMock(message=MagicMock(content=text))]
    m.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    return m


def _alert() -> Alert:
    return Alert(file="x.h", line=1, col=1, severity="warning",
                 check_name="c", message="m")


def test_high_confidence_skips_second_pass(monkeypatch):
    """高置信度(≥0.8)→ 一票定案,不触发二次判定(省钱验证)。"""
    monkeypatch.setattr(cli, "build_context", lambda alert, repo: "")
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _msg('{"decision": "ignore", "reason": "r", "confidence": 0.9}')]
    r = cli.judge_one(client, _alert(), "/tmp/nope", {})
    assert client.chat.completions.create.call_count == 1       # 只判一次
    assert r.passes == 1
    assert r.judgement.decision == "ignore"


def test_low_confidence_triggers_second_pass(monkeypatch):
    """低置信度(<0.8)→ 带使用侧证据重判一次,二次判定为准。"""
    monkeypatch.setattr(cli, "build_context", lambda alert, repo: "")
    monkeypatch.setattr(cli, "names_defined_in", lambda path, repo: {"Get"})   # 嫌疑名单
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _msg('{"decision": "suspicious", "reason": "ev", "confidence": 0.6}'),
        _msg('{"decision": "real", "reason": "use-side", "confidence": 0.95}')]
    r = cli.judge_one(client, _alert(), "/tmp/nope", {"Get": ["main.cc:17"]})
    assert client.chat.completions.create.call_count == 2       # 触发二判
    assert r.passes == 2
    assert r.judgement.decision == "real"                        # 二次判定为准
