"""P10 工具调用 Agent 消融: 动态证据拉取(T/T-lite) vs 静态预取(B 臂基线)

单变量: 证据怎么进 prompt。判定集 / rubric 判定标准 / 模型 / 温度 / 解析 / 评分
全部与 B 臂一致;基线复用 eval/results/juliet_arm_llm.jsonl(不重跑,与 P9 同策,
模型漂移问题在报告注明)。

臂:
  T      = agentic loop(源码工具 + KB 工具)。KB 用最强配置(hybrid × cwe_bi,
           P7 检准率 37.3%): agentic 自主选择下 KB 仍无增益 → 知识注入假说彻底闭环。
  T-lite = agentic loop 仅源码工具(无 KB),把 P6/P7"KB 边际≈0"搬进 agentic 设置复验。

用法:
  python eval/run_agentic.py --arm Tlite --limit 8     # 冒烟(不碰 chroma)
  python eval/run_agentic.py --arm all                 # 全量 451

产物: eval/results/juliet_arm_agentic{,_nokb}.jsonl
  每行 = 标注行 + decision/confidence/reason/usage/rounds/tool_trace/tool_chars
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── R1 铁律:任何 LLM 库 import 之前清代理 ──
for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))    # 认祖(cpp_sentinel)

from openai import OpenAI

import run_juliet as RJ                                        # 同磅秤单源: LABELS/RUBRIC
from cpp_sentinel.agentic import (TOOLS_FULL, TOOLS_NOKB, ToolBox,
                                 agentic_judge, agentic_rubric)
from cpp_sentinel.metrics import compute_metrics

RESULTS = RJ.RESULTS
RUBRIC = agentic_rubric(RJ.RUBRIC)      # 判定标准逐字同 B 臂,只加"取证方式"一节


def judge_row(client, row: dict, tools: list, retriever, max_rounds: int) -> dict:
    """单条: 成功 → agentic_judge 结果;API 级故障 → 同 judge_one 口径记 unsure,不崩。"""
    tb = ToolBox(row, retriever=retriever)
    try:
        return {**row, **agentic_judge(client, row, tb, tools, RUBRIC, max_rounds)}
    except Exception as e:
        return {**row, "decision": "unsure", "confidence": -1,
                "reason": f"{type(e).__name__}: {e}", "usage": {},
                "rounds": 0, "tool_trace": tb.trace, "tool_chars": tb.tool_chars}


def run_arm(client, name: str, tools: list, retriever, rows: list,
            max_rounds: int, workers: int) -> list[dict]:
    """断点续跑: 已有结果里 usage 非空(判定成功)的行不重跑 —— 402 余额事故后
    不该为已成功行再花一次钱;402/429 失败行(usage={})自动补跑。"""
    path = RESULTS / f"juliet_arm_{name}.jsonl"
    done = {}
    if path.exists():
        for l in path.read_text().splitlines():
            r = json.loads(l)
            if r.get("usage"):
                done[(r["file"], r["line"], r["check"])] = r
    todo = [r for r in rows if (r["file"], r["line"], r["check"]) not in done]
    if done:
        print(f"  {name}: 续跑,已有 {len(done)} 条有效,补跑 {len(todo)} 条")
    t0 = time.perf_counter()
    out = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(judge_row, client, r, tools, retriever, max_rounds): i
                for i, r in enumerate(todo)}
        for fut in as_completed(futs):
            out.append(fut.result())
            print(f"  {name}: {len(out)}/{len(todo)}", end="\r")
    fresh = {(r["file"], r["line"], r["check"]): r for r in out}
    rows_out = [done.get((r["file"], r["line"], r["check"])) or
                fresh[(r["file"], r["line"], r["check"])] for r in rows]
    RESULTS.mkdir(exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows_out) + "\n")
    dt = time.perf_counter() - t0
    tokens = sum(r["usage"].get("prompt_tokens", 0) + r["usage"].get("completion_tokens", 0)
                 for r in rows_out if r["usage"])
    calls = sum(len(r["tool_trace"]) for r in rows_out)
    rounds = sum(r["rounds"] for r in rows_out)
    print(f"\n  {name} 完成: {len(rows_out)} 条, {dt:.0f}s, token {tokens:,}, "
          f"工具调用 {calls} 次(均 {calls/len(rows_out):.1f}/条), 均 {rounds/len(rows_out):.1f} 轮")
    return rows_out


def show(name: str, rows_out: list[dict]) -> None:
    """指标 + 工具使用分布(副产物: LLM 自主取证到底用什么)。"""
    gold = [r["label"] for r in rows_out]
    print(f"  [{name}] {compute_metrics(gold, [r['decision'] for r in rows_out])}")
    dist = Counter(t["tool"] for r in rows_out for t in r["tool_trace"])
    if dist:
        print(f"  工具分布: {dict(dist)}")
    unsure = sum(1 for r in rows_out if r["decision"] == "unsure")
    if unsure:
        print(f"  ⚠ unsure {unsure} 条(API 故障/解析失败,口径与 B 臂一致按未判处理)")


def baseline_for(rows: list[dict]) -> None:
    """B 臂基线,同子集复算(全量时应精确复现 P4 数字 P0.889/R0.720/F1 0.796)。"""
    base = [json.loads(l) for l in (RESULTS / "juliet_arm_llm.jsonl").read_text().splitlines()]
    keys = {(r["file"], r["line"], r["check"]) for r in rows}
    sub = [r for r in base if (r["file"], r["line"], r["check"]) in keys]
    tokens = sum(r["usage"].get("prompt_tokens", 0) + r["usage"].get("completion_tokens", 0)
                 for r in sub if r.get("usage"))
    print(f"  [B 基线同子集 n={len(sub)}] "
          f"{compute_metrics([r['label'] for r in sub], [r['decision'] for r in sub])}, "
          f"token {tokens:,}")


def main():
    ap = argparse.ArgumentParser(description="P10 agentic 消融")
    ap.add_argument("--arm", choices=["T", "Tlite", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0, help="只判前 N 条(冒烟用)")
    ap.add_argument("--max-rounds", type=int, default=6)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    rows = RJ.LABELS[: args.limit] if args.limit else RJ.LABELS
    bugs = sum(1 for r in rows if r["label"] == "bug")
    print(f"判定集 {len(rows)} 条(bug {bugs}/noise {len(rows) - bugs})")
    baseline_for(rows)

    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("请先设置: export DEEPSEEK_API_KEY=<你的key>")
    client = OpenAI(base_url="https://api.deepseek.com/v1",
                    api_key=os.environ["DEEPSEEK_API_KEY"])

    if args.arm in ("T", "all"):
        from cpp_sentinel.retrieval import Retriever
        retr = Retriever("hybrid", collection="cwe_bi")   # 主线程建一次(chroma 初始化竞态,见 run_juliet)
        print("=== T 臂: agentic(源码工具 + KB[hybrid×cwe_bi]) ===")
        show("T", run_arm(client, "agentic", TOOLS_FULL, retr, rows,
                          args.max_rounds, args.workers))

    if args.arm in ("Tlite", "all"):
        print("=== T-lite 臂: agentic(仅源码工具) ===")
        show("T-lite", run_arm(client, "agentic_nokb", TOOLS_NOKB, None, rows,
                               args.max_rounds, args.workers))


if __name__ == "__main__":
    main()
