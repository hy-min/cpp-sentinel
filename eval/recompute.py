"""v1/v2/v3 全版本对比:同一道题,三次迭代,一表看尽"""
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

versions = [
    ("A 臂(裸静态)", None, ["bug"] * len(labels) or None),   # 处理 null
]
# A 臂直接用假预测
print("=== A 臂(裸静态)===")
print(compute_metrics(gold, ["bug"] * len(labels)))

for name, label in [
    ("arm_llm.jsonl", "B 臂 v1(无证据无规则)"),
    ("arm_llm_v2.jsonl", "B 臂 v2(+强谓词规则)"),
    ("arm_llm_v3.jsonl", "B 臂 v3(+源码证据)"),
    ("arm_rag_v3.jsonl", "C 臂 v3(+源码证据+RAG)"),
]:
    preds = load(name)
    if preds is not None:
        print(f"\n=== {label} ===")
        print(compute_metrics(gold, preds))
