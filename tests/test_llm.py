"""llm_config 的测试 —— provider 可换(DeepSeek 默认 / GLM 等 OpenAI 兼容端点)。"""
from unittest.mock import MagicMock

from cpp_sentinel.cli import call_with_retry
from cpp_sentinel.llm import llm_config
from cpp_sentinel.report import cost_cny, to_markdown


def test_default_is_deepseek(monkeypatch):
    monkeypatch.delenv("CPP_SENTINEL_BASE_URL", raising=False)
    monkeypatch.delenv("CPP_SENTINEL_MODEL", raising=False)
    monkeypatch.delenv("CPP_SENTINEL_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    base, model, key = llm_config()
    assert "deepseek" in base and model == "deepseek-chat" and key == "ds-key"


def test_cpp_sentinel_env_overrides(monkeypatch):
    """三件套全覆盖: GLM 等任意 OpenAI 兼容端点可切。"""
    monkeypatch.setenv("CPP_SENTINEL_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
    monkeypatch.setenv("CPP_SENTINEL_MODEL", "glm-5.3-flash")
    monkeypatch.setenv("CPP_SENTINEL_API_KEY", "glm-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")     # 新变量优先于回落
    assert llm_config() == ("https://open.bigmodel.cn/api/paas/v4/", "glm-5.3-flash", "glm-key")


def test_call_with_retry_uses_env_model(monkeypatch):
    """call_with_retry 的 model 参数跟着 env 走(切 provider 不改调用方)。"""
    monkeypatch.setenv("CPP_SENTINEL_MODEL", "glm-5.3-flash")
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content="ok"))]
    resp.usage = MagicMock(prompt_tokens=1, completion_tokens=1)
    client.chat.completions.create.return_value = resp
    call_with_retry(client, [{"role": "user", "content": "hi"}])
    assert client.chat.completions.create.call_args.kwargs["model"] == "glm-5.3-flash"


def test_reasoning_effort_wiring(monkeypatch):
    """GLM-5 系始终思考: reasoning_effort=low 经 extra_body 透传(2s vs 14s 实测);
    未设置时不传该参数(DeepSeek 等端点的安全默认)。"""
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content="ok"))]
    resp.usage = MagicMock(prompt_tokens=1, completion_tokens=1)
    client.chat.completions.create.return_value = resp

    monkeypatch.setenv("CPP_SENTINEL_REASONING_EFFORT", "low")
    call_with_retry(client, [{"role": "user", "content": "hi"}])
    assert client.chat.completions.create.call_args.kwargs["extra_body"] == \
        {"reasoning_effort": "low"}

    monkeypatch.delenv("CPP_SENTINEL_REASONING_EFFORT")
    call_with_retry(client, [{"role": "user", "content": "hi"}])
    assert "extra_body" not in client.chat.completions.create.call_args.kwargs


def test_cost_only_priced_for_known_models(monkeypatch):
    """DeepSeek → ¥ 估计;未知模型(如 GLM)→ None,不打误导性价格(诚实挂账)。"""
    monkeypatch.setenv("CPP_SENTINEL_MODEL", "deepseek-chat")
    assert cost_cny(1000, 1000) == 0.010
    monkeypatch.setenv("CPP_SENTINEL_MODEL", "glm-5.3-flash")
    assert cost_cny(1000, 1000) is None
    report = {"total": 0, "summary": {"real": 0, "suspicious": 0, "ignore": 0, "failed": 0},
              "entries": [], "failed": [],
              "usage": {"prompt_tokens": 100, "completion_tokens": 50}, "second_pass": 0}
    assert "以模型方账单为准" in to_markdown(report)
