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

def source_snippet(file: str, line: int, span: int = 4) -> str:
    """v3:读取告警行 ±4 行的源码,当'证据切片'给 LLM 看"""
    p = Path(file)
    if not p.exists():
        return "(源文件不可读)"
    lines = p.read_text(errors="ignore").splitlines()
    lo, hi = max(0, line - span), min(len(lines), line + span)
    return "\n".join(f"{i+1}: {lines[i]}" for i in range(lo, hi))


def llm_judge(use_rag: bool):
    """B/C 臂:LLM 逐条判;use_rag 控制是否附带知识库条款"""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("请先设置: export DEEPSEEK_API_KEY=<你的key>")
    client = OpenAI(base_url="https://api.deepseek.com/v1",
                    api_key=os.environ["DEEPSEEK_API_KEY"])
    preds = []
    for row in LABELS:
        alert = (f"{row['file']}:{row['line']}: {row['check']}\n{row['message']}")
        ctx = []
        if use_rag:                                             # C 臂多一步:查知识库
            import chromadb
            chroma = chromadb.PersistentClient(path=str(Path("/home/hy/dkvstore") / "data" / "chroma"))
            col = chroma.get_or_create_collection("cwe")
            hit = col.query(query_texts=[row["message"]], n_results=1)
            if hit["ids"][0]:
                ctx.append("相关规范: " + hit["metadatas"][0][0]["title"])
        ctx.append("=== 源码证据 ===\n" + source_snippet(row["file"], row["line"]))
        ctx = "\n".join(ctx)
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
=== 强谓词规则(重要) ===
- 若 check 名含 optional 且 message 描述"未检查访问"(unchecked access),或属 clang-analyzer
  的内存安全类,或 message 含 accessing/memory/overflow 等词:除非有明确反证,应判 real 或 suspicious,
  不要判 ignore —— 宁可保守,不可漏检。
只输出 JSON: {"decision": "...", "reason": "一句话理由", "confidence": 0.x}"""

def main():
    gold = [r["label"] for r in LABELS]
    print("=== A 臂: 裸静态(全报) ===")
    print(compute_metrics(gold, arm_static()))
    print("\n=== B 臂: +LLM ===")
    preds_b = llm_judge(use_rag=False)
    (ROOT / "eval" / "results").mkdir(exist_ok=True)
    (ROOT / "eval" / "results" / "arm_llm_v3.jsonl").write_text(json.dumps(preds_b))   # v3(源码证据)
    print(compute_metrics(gold, preds_b))
    print("\n=== C 臂: +LLM+RAG (v3 规则) ===")
    preds_c = llm_judge(use_rag=True)
    (ROOT / "eval" / "results" / "arm_rag_v3.jsonl").write_text(json.dumps(preds_c))
    print(compute_metrics(gold, preds_c))

if __name__ == "__main__":
    main()
