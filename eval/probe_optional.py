"""定向实验:给足源码证据后,LLM 能否抓住 idx6(optional 未检查)?"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # 认祖(同其他 eval 脚本)

for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)

from openai import OpenAI
from cpp_sentinel.review import parse_response

RUBRIC = """你是 C++ 静态审查助手。判定: real(真问题)/ suspicious(疑似)/ ignore(忽略)。\n只输出 JSON: {"decision": "...", "reason": "...", "confidence": 0.x}"""

PROMPT = f"""{RUBRIC}

=== 告警 ===
status.h:67 bugprone-unchecked-optional-access
unchecked access to optional value

=== 源码证据(标注员实际看到的东西) ===
status.h:66-68:
    const T& Value() const {{ return value_.value(); }}
失败路径示例: Client::Get 中
    if (!resp.status.IsOk()) {{ return Result<std::string>(resp.status); }}
    // 若调用方随后 .Value() → optional 为空 → std::bad_optional_access(UB)

请判定。"""

client = OpenAI(base_url="https://api.deepseek.com/v1",
                api_key=os.environ["DEEPSEEK_API_KEY"])
resp = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": PROMPT}], temperature=0)
print(parse_response(resp.choices[0].message.content))
