"""三臂消融: A=裸静态 / B=+LLM / C=+LLM+RAG → 同一"磅秤"出分"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))    # 认祖(同 dump_alerts.py)

for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)                                     # R1 铁律

from openai import OpenAI

from cpp_sentinel.metrics import compute_metrics
from cpp_sentinel.review import build_prompt, parse_response

ROOT = Path(__file__).resolve().parents[1]
LABELS = [json.loads(l) for l in (ROOT / "eval" / "dataset" / "labels.jsonl").read_text().splitlines()]

def arm_static():
    """A 臂:所有告警都判'bug'(静态工具全报,不做鉴别)"""
    return ["bug"] * len(LABELS)                                # 全枪毙=全报

def llm_judge(use_rag: bool):
    """B/C 臂:LLM 逐条判;use_rag 控制是否附带知识库条款"""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("请先设置: export DEEPSEEK_API_KEY=<你的key>")
    client = OpenAI(base_url="https://api.deepseek.com/v1",
                    api_key=os.environ["DEEPSEEK_API_KEY"])
    preds = []
    for row in LABELS:
        alert = (f"{row['file']}:{row['line']}: {row['check']}\n{row['message']}")
        ctx = ""
        if use_rag:                                             # C 臂多一步:查知识库
            import chromadb
            chroma = chromadb.PersistentClient(path=str(Path("/home/hy/dkvstore") / "data" / "chroma"))
            col = chroma.get_or_create_collection("cwe")
            hit = col.query(query_texts=[row["message"]], n_results=1)
            ctx = "相关规范: " + hit["metadatas"][0][0]["title"] if hit["ids"][0] else ""
        prompt = f"{RUBRIC}\n\n=== 告警 ===\n{alert}\n=== 背景 ===\n{ctx}"
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        try:
            preds.append(parse_response(resp.choices[0].message.content).decision)
        except ValueError:
            preds.append("unsure")                              # 乱答=没判(计漏)
        print(f"  {len(preds)}/{len(LABELS)}", end="\r")
    print()
    return preds

RUBRIC = """你是 C++ 静态审查助手。针对告警与上下文,判定:
- real: 证据充分(如:被广泛调用、路径可达、符合 CWE)→ 真问题
- suspicious: 证据不足,值得人工再看
- ignore: 误报/风格问题
只输出 JSON: {"decision": "...", "reason": "一句话理由", "confidence": 0.x}"""

def main():
    gold = [r["label"] for r in LABELS]
    print("=== A 臂: 裸静态(全报) ===")
    print(compute_metrics(gold, arm_static()))
    print("\n=== B 臂: +LLM ===")
    preds_b = llm_judge(use_rag=False)
    (ROOT / "eval" / "results").mkdir(exist_ok=True)
    (ROOT / "eval" / "results" / "arm_llm.jsonl").write_text(json.dumps(preds_b))
    print(compute_metrics(gold, preds_b))
    print("\n=== C 臂: +LLM+RAG ===")
    preds_c = llm_judge(use_rag=True)
    (ROOT / "eval" / "results" / "arm_rag.jsonl").write_text(json.dumps(preds_c))
    print(compute_metrics(gold, preds_c))

if __name__ == "__main__":
    main()
