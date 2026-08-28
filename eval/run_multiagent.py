"""P9 多 Agent 拆分消融: triager(初筛) → reviewer(现判定) → fixer(补丁)

同 451 判定集;reviewer 复用 run_juliet.judge_one(B 臂同 rubric 同证据)——
单级 vs 多级是唯一变量。短路规则: triage=ignore 且置信≥0.9 → 不交 reviewer。

用法: conda run -n cpp-review python eval/run_multiagent.py
产物: eval/results/juliet_arm_multiagent.jsonl
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)

from openai import OpenAI

from run_juliet import RUBRIC, judge_one, source_snippet    # B 臂同款,保证可比
from cpp_sentinel.agents import fix, triage
from cpp_sentinel.metrics import compute_metrics

LABELS = [json.loads(l) for l in (HERE / "dataset" / "labels_juliet.jsonl").read_text().splitlines()]
SHORT_CIRCUIT_CONF = 0.9     # 初筛高置信 ignore 才短路(宁可多审,不可错杀)
WORKERS = 8


def _merge_usage(usages: list[dict]) -> dict:
    out = {"prompt_tokens": 0, "completion_tokens": 0}
    for u in usages:
        if u:
            out["prompt_tokens"] += u.get("prompt_tokens", 0)
            out["completion_tokens"] += u.get("completion_tokens", 0)
    return out


def pipeline(client, row: dict) -> dict:
    try:
        tri, u1 = triage(client, row)
        usages = [u1]
        if tri.decision == "ignore" and tri.confidence >= SHORT_CIRCUIT_CONF:
            return {**row, "triage_decision": tri.decision, "triage_conf": tri.confidence,
                    "reviewed": False, "decision": "ignore", "confidence": tri.confidence,
                    "patch": False, "usage": _merge_usage(usages)}
        rev = judge_one(client, row, use_rag=False)         # B 臂同款判定
        usages.append(rev.get("usage"))
        patched = False
        if rev["decision"] == "real":                       # fixer 只在真问题上动
            _text, u3 = fix(client, row, source_snippet(row["file"], row["line"]))
            usages.append(u3)
            patched = True
        return {**row, "triage_decision": tri.decision, "triage_conf": tri.confidence,
                "reviewed": True, "decision": rev["decision"],
                "confidence": rev["confidence"], "patch": patched,
                "usage": _merge_usage(usages)}
    except Exception as e:
        return {**row, "triage_decision": "error", "triage_conf": -1,
                "reviewed": False, "decision": "unsure", "confidence": -1,
                "patch": False, "usage": {}, "reason": f"{type(e).__name__}: {e}"}


def main():
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("请先设置: export DEEPSEEK_API_KEY=<你的key>")
    client = OpenAI(base_url="https://api.deepseek.com/v1",
                    api_key=os.environ["DEEPSEEK_API_KEY"])
    gold = [r["label"] for r in LABELS]
    t0 = time.perf_counter()
    out = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(pipeline, client, r): i for i, r in enumerate(LABELS)}
        for fut in as_completed(futs):
            out.append((futs[fut], fut.result()))
            print(f"  multiagent: {len(out)}/{len(LABELS)}", end="\r")
    out.sort(key=lambda x: x[0])
    rows = [r for _, r in out]

    (HERE.parent / "eval" / "results").mkdir(exist_ok=True)
    (HERE / "results" / "juliet_arm_multiagent.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")

    n_short = sum(1 for r in rows if not r["reviewed"])
    tokens = sum(r["usage"].get("prompt_tokens", 0) + r["usage"].get("completion_tokens", 0)
                 for r in rows if r["usage"])
    print(f"\n多级管线完成: {len(rows)} 条, {time.perf_counter()-t0:.0f}s, "
          f"token 合计 {tokens:,}, 短路率 {n_short/len(rows)*100:.0f}%, "
          f"出补丁 {sum(1 for r in rows if r['patch'])} 条")

    print("=== 多级管线(终判) ===")
    print(compute_metrics(gold, [r["decision"] for r in rows]))
    print("=== 对照: 单级 B 臂 ===")
    rows_b = [json.loads(l) for l in open(HERE / "results" / "juliet_arm_llm.jsonl")]
    tokens_b = sum(r["usage"].get("prompt_tokens", 0) + r["usage"].get("completion_tokens", 0)
                   for r in rows_b if r.get("usage"))
    print(compute_metrics(gold, [r["decision"] for r in rows_b]),
          f"(token 合计 {tokens_b:,})")
    print("=== 参考: triager 单级(若不送审) ===")
    print(compute_metrics(gold, [r["triage_decision"] for r in rows]))


if __name__ == "__main__":
    main()
