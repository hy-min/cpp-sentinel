"""LLM provider 配置: 默认 DeepSeek,环境变量可切任意 OpenAI 兼容端点(GLM 等)。

    CPP_SENTINEL_API_KEY   —— 未设时回落 DEEPSEEK_API_KEY(历史脚本零改动)
    CPP_SENTINEL_BASE_URL  —— 默认 https://api.deepseek.com/v1;GLM: https://open.bigmodel.cn/api/paas/v4/
    CPP_SENTINEL_MODEL     —— 默认 deepseek-chat

每次调用时读 env(不在 import 时冻结): 测试可 monkeypatch,CI 可按步骤切换。
"""
import os

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


def llm_config() -> tuple[str, str, str]:
    """返回 (base_url, model, api_key)。"""
    return (
        os.environ.get("CPP_SENTINEL_BASE_URL", DEFAULT_BASE_URL),
        os.environ.get("CPP_SENTINEL_MODEL", DEFAULT_MODEL),
        os.environ.get("CPP_SENTINEL_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", ""),
    )


def reasoning_effort() -> str | None:
    """CPP_SENTINEL_REASONING_EFFORT: GLM-5 系始终思考,可调 low/high/max。
    low 实测 2s/36 tokens vs 默认 14s/539 tokens(判断类任务够用,成本降 15 倍)。
    None = 不传该参数(DeepSeek 等不支持端点的安全默认)。"""
    return os.environ.get("CPP_SENTINEL_REASONING_EFFORT") or None
