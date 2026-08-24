"""v1 vs v2 对比:强谓词规则前后,同一道题重测"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cpp_sentinel.metrics import compute_metrics

ROOT = Path(__file__).resolve().parents[1]
labels = [json.loads(l) for l in (ROOT / "eval" / "dataset" / "labels.jsonl").read_text().splitlines()]
gold = [r["label"] for r in labels]

def load(name: str):
    p = ROOT / "eval" / "results" / name
    return json.loads(p.read_text()) if p.exists() else None

static = ["bug"] * len(labels)
llm_v1 = load("arm_llm.jsonl")          # 旧:无强谓词规则
llm_v2 = load("arm_llm_v2.jsonl")       # 新:有强谓词规则
rag_v2 = load("arm_rag_v2.jsonl")

print("=== A 臂(裸静态)==="); print(compute_metrics(gold, static))
if llm_v1:
    print("\n=== B 臂 v1(无强谓词)==="); print(compute_metrics(gold, llm_v1))
if llm_v2:
    print("\n=== B 臂 v2(强谓词)==="); print(compute_metrics(gold, llm_v2))
if rag_v2:
    print("\n=== C 臂 v2(强谓词+RAG)==="); print(compute_metrics(gold, rag_v2))
