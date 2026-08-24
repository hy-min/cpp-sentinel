"""v6:只重跑 C 臂(50 条大库 RAG)——B 臂无变化,不重烧 API"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)

from cpp_sentinel.metrics import compute_metrics
from eval.run_eval import LABELS, llm_judge

preds = llm_judge(use_rag=True)                    # 与 v5 C 臂唯一的差别:知识库现在有 50 条
(Path(__file__).resolve().parents[1] / "eval" / "results" / "arm_rag_v6.jsonl").write_text(json.dumps(preds))

gold = [r["label"] for r in LABELS]
print(compute_metrics(gold, preds))
