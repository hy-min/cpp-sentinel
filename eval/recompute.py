"""用已保存的 LLM 判断 + 最新标注,直接重算三臂(不再烧 API)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cpp_sentinel.metrics import compute_metrics

ROOT = Path(__file__).resolve().parents[1]
labels = [json.loads(l) for l in (ROOT / "eval" / "dataset" / "labels.jsonl").read_text().splitlines()]
gold = [r["label"] for r in labels]                          # 最新金标准(含 P1=bug)

static = ["bug"] * len(labels)                               # A 臂:全报
llm = json.loads((ROOT / "eval" / "results" / "arm_llm.jsonl").read_text())   # B 臂(已存)
rag = json.loads((ROOT / "eval" / "results" / "arm_rag.jsonl").read_text())   # C 臂(已存)

print("=== A 臂:裸静态(全报)==="); print(compute_metrics(gold, static))
print("=== B 臂:+LLM ===\n"); print(compute_metrics(gold, llm))
print("=== C 臂:+LLM+RAG ==="); print(compute_metrics(gold, rag))
