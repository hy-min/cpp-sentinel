"""v5 管线 debug:完整复刻 idx6 的请求,打印 LLM 原始回答看它到底怎么想"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)

from openai import OpenAI
from eval.run_eval import usage_side, source_snippet, RUBRIC

ROOT = Path(__file__).resolve().parents[1]
row = json.loads(Path("eval/dataset/labels.jsonl").read_text().splitlines()[6])   # idx6

alert = f"{row['file']}:{row['line']}: {row['check']}\n{row['message']}"
ctx = "\n".join([
    "=== 源码证据 ===\n" + source_snippet(row["file"], row["line"]),
    "=== 使用侧证据(跨文件) ===\n" + usage_side(row["file"]),
])
prompt = f"{RUBRIC}\n\n=== 告警 ===\n{alert}\n=== 背景 ===\n{ctx}"

client = OpenAI(base_url="https://api.deepseek.com/v1",
                api_key=os.environ["DEEPSEEK_API_KEY"])
resp = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": prompt}], temperature=0)

print("===== LLM 原始回答 =====")
print(resp.choices[0].message.content)
print("===== prompt 长度 ===== ", len(prompt))
