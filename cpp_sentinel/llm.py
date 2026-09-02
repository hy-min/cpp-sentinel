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
