"""定向实验 v5:同时给'告警文件全文 + 真实使用侧(失败路径行)',LLM 能否判 real?"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)

from openai import OpenAI
from cpp_sentinel.review import parse_response

ROOT = Path(__file__).resolve().parents[1]
status_h = json.loads((ROOT / "eval" / "dataset" / "labels.jsonl").read_text().splitlines()[6])   # idx6 原始行,只是为了别手打路径
status_file = Path(status_h["file"])

RUBRIC = """你是 C++ 静态审查助手。判定: real(真问题)/ suspicious(疑似)/ ignore(忽略)。\n只输出 JSON: {"decision": "...", "reason": "...", "confidence": 0.x}"""

client = OpenAI(base_url="https://api.deepseek.com/v1",
                api_key=os.environ["DEEPSEEK_API_KEY"])

# 证据 A: 告警文件全文(真实读取)
src = status_file.read_text(errors="ignore")
# 证据 B: 真实使用侧(从 client.cc 摘取失败路径构造,原样文本)
usage_side = """    auto resp = Send(req);
    if (!resp.status.IsOk()) {
        return Result<std::string>(resp.status);   // 失败路径:仅 Status 构造,optional 为空
    }"""

PROMPT = f"""{RUBRIC}

=== 告警 ===
{status_file}:67 bugprone-unchecked-optional-access
unchecked access to optional value

=== 证据 A: 告警文件全文 ===
{src}

=== 证据 B: 真实使用侧(client.cc,失败路径) ===
{usage_side}

请判定。"""

resp = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": PROMPT}], temperature=0)
print(parse_response(resp.choices[0].message.content))
