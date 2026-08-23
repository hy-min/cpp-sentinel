import os
for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)                    # R1:任何 LLM 库 import 之前清代理(仓库铁律)

from openai import OpenAI                      # API 客户端
from cpp_sentinel.models import Alert          # 课1产物
from cpp_sentinel.review import build_prompt, parse_response   # 课4产物

if not os.environ.get("DEEPSEEK_API_KEY"):
    raise SystemExit("请先设置: export DEEPSEEK_API_KEY=<你的key>")

alert = Alert(
    file="/home/hy/dkvstore/include/dkvstore/common/status.h",
    line=9, col=12, severity="warning",
    check_name="performance-enum-size",
    message="enum 'ErrorCode' uses a larger base type ('uint16_t') than necessary",
)
context = "Status 类被 300+ 处使用,该告警字段影响面大,但也可能只是内存 1 字节的小节约。"

client = OpenAI(base_url="https://api.deepseek.com/v1",
                api_key=os.environ["DEEPSEEK_API_KEY"])

resp = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": build_prompt(alert, context)}],
    temperature=0,
)
text = resp.choices[0].message.content
print("LLM 原始回话:\n", text, "\n")

judgement = parse_response(text)               # 剪刀 + 校验(课4的关卡!)
print("判定: real/suspicious/ignore →", judgement.decision)
print("理由:", judgement.reason)
print("置信度:", judgement.confidence)
