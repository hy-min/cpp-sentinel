"""Juliet 规模化三臂评估: A=裸静态 / B=+LLM / C=+LLM+RAG —— 同一把磅秤,371 条标注告警

与 run_eval.py(dkvstore)的区别:Juliet 用例单文件自包含,无跨文件使用侧证据可挖
→ 证据 = 全文件源码(文件 <120 行时全文);单遍判定,记录置信度供校准分析。
判定子集: eval/dataset/labels_juliet.jsonl (prepare_juliet.py 生成, seed=42)

用法: conda run -n cpp-review python eval/run_juliet.py [--arm A|B|C|all]
产物: eval/results/juliet_arm_{llm,llm_rag}.jsonl (含 gold/decision/confidence/reason)
"""
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))    # 认祖

for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)                                     # R1 铁律

from openai import OpenAI

from cpp_sentinel.cli import call_with_retry                    # 复用:重试/降级/token 账单
from cpp_sentinel.metrics import compute_metrics
from cpp_sentinel.review import parse_response

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "eval" / "dataset" / "labels_juliet.jsonl"
RESULTS = ROOT / "eval" / "results"
CHROMA = "/home/hy/cpp-sentinel/data/chroma"                    # 50 条真实 CWE 语料(v6 同款;
                                                                 # dkvstore 下的库已空,勿指错)
WORKERS = 8

LABELS = [json.loads(l) for l in DATASET.read_text().splitlines()]

# 与 run_eval.py v7 完全同款的评分细则(含强谓词规则)——保证与 dkvstore 结果可比
RUBRIC = """你是 C++ 静态审查助手。针对告警与上下文,判定:
- real: 证据充分(如:被广泛调用、路径可达、符合 CWE)→ 真问题
- suspicious: 证据不足,值得人工再看
- ignore: 误报/风格问题
=== 强谓词规则(重要) ===
- 若 check 名含 optional 且 message 描述"未检查访问"(unchecked access),或属 clang-analyzer
  的内存安全类,或 message 含 accessing/memory/overflow 等词:除非有明确反证,应判 real 或 suspicious,
  不要判 ignore —— 宁可保守,不可漏检。
只输出 JSON: {"decision": "...", "reason": "一句话理由", "confidence": 0.x}"""

# v2(2026-08-26): 治 fn 归因发现的两个模式——"测试用例豁免"心理 + check 语义错位限缩。
# 单变量对照:同子集、同模型,只换 rubric。
RUBRIC_V2 = RUBRIC.replace(
    '只输出 JSON',
    """=== 判定对象校准(重要) ===
- 判定对象是告警指向代码路径的**实际后果**:自包含/演示/测试用例中的缺陷也是缺陷,
  不得因"这是测试代码"豁免;无外部调用证据不等于无缺陷,以文件内数据流为准。
- 若告警的 check 语义与该行的实际风险不一致,以代码路径的实际后果为准。
只输出 JSON""")


def source_snippet(file: str, line: int, span: int = 25) -> str:
    """与 run_eval.py 同款:短文件全文,长文件 ±span 行窗口。"""
    p = Path(file)
    if not p.exists():
        return "(源文件不可读)"
    lines = p.read_text(errors="ignore").splitlines()
    if len(lines) <= 120:
        return "\n".join(f"{i+1}: {lines[i]}" for i in range(len(lines)))
    lo, hi = max(0, line - span), min(len(lines), line + span)
    return "\n".join(f"{i+1}: {lines[i]}" for i in range(lo, hi))


_CHROMA_COL = None
_CHROMA_LOCK = threading.Lock()


def rag_collection():
    """chroma 集合的惰性单例——PersistentClient 并发初始化会踩 RustBindings 竞态
    (AttributeError: 'RustBindingsAPI' object has no attribute 'bindings'),串行建一次后共享。"""
    global _CHROMA_COL
    if _CHROMA_COL is None:
        with _CHROMA_LOCK:
            if _CHROMA_COL is None:
                import chromadb
                client = chromadb.PersistentClient(path=CHROMA)
                _CHROMA_COL = client.get_or_create_collection("cwe")
    return _CHROMA_COL


def rag_context(message: str, retriever=None) -> tuple[str, str]:
    """C 臂:知识库检索相关 CWE 条款。retriever=None 走 v6 同款向量路径(保持基线可比);
    传入 Retriever 则按其模式(向量/BM25/RRF)检索。返回(上下文本, 检中条目调试信息)。"""
    if retriever is None:
        col = rag_collection()
        hit = col.query(query_texts=[message], n_results=1)
        if hit["ids"][0]:
            return "相关规范: " + hit["metadatas"][0][0]["title"], f"vector:top1={hit['ids'][0][0]}"
        return "", "vector:no-hit"
    title, _doc, dbg = retriever.query(message)
    if title:
        return "相关规范: " + title, dbg
    return "", dbg


def judge_one(client, row: dict, use_rag: bool, rubric: str = RUBRIC, retriever=None,
              extra_ctx: str = "") -> dict:
    """单条判定:源码证据(±RAG ±额外上下文如反馈记忆)→ LLM;乱答/异常如实记 unsure,不崩。"""
    alert = f"{row['file']}:{row['line']}: {row['check']}\n{row['message']}"
    ctx = []
    retrieved = ""
    if use_rag:
        r, retrieved = rag_context(row["message"], retriever)
        if r:
            ctx.append(r)
    ctx.append("=== 源码证据 ===\n" + source_snippet(row["file"], row["line"]))
    if extra_ctx:
        ctx.append(extra_ctx)                           # P12: 历史人工复核 few-shot
    prompt = f"{rubric}\n\n=== 告警 ===\n{alert}\n=== 背景 ===\n" + "\n".join(ctx)
    try:
        text, tries, usage = call_with_retry(client, [{"role": "user", "content": prompt}])
        c = parse_response(text)
        return {**row, "decision": c.decision, "confidence": c.confidence,
                "reason": c.reason, "usage": usage, "retrieved": retrieved}
    except Exception as e:
        return {**row, "decision": "unsure", "confidence": -1,
                "reason": f"{type(e).__name__}: {e}", "usage": {}, "retrieved": retrieved}


def run_arm(client, name: str, use_rag: bool, rubric: str = RUBRIC, retriever=None) -> list[dict]:
    t0 = time.perf_counter()
    out = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(judge_one, client, r, use_rag, rubric, retriever): i for i, r in enumerate(LABELS)}
        for fut in as_completed(futs):
            out.append((futs[fut], fut.result()))
            print(f"  {name}: {len(out)}/{len(LABELS)}", end="\r")
    out.sort(key=lambda x: x[0])
    rows = [r for _, r in out]
    tokens = sum(r["usage"].get("prompt_tokens", 0) + r["usage"].get("completion_tokens", 0)
                 for r in rows if r["usage"])
    print(f"\n  {name} 完成: {len(rows)} 条, {time.perf_counter() - t0:.0f}s, "
          f"token 合计 {tokens:,}")
    (RESULTS).mkdir(exist_ok=True)
    (RESULTS / f"juliet_arm_{name}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    return rows


def calibration(rows: list[dict]) -> None:
    """置信度校准: 分桶 → 桶内准确率 vs 平均置信度(可靠性表)。"""
    ALIAS = {"real": "bug", "ignore": "noise", "suspicious": "unsure"}
    buckets = [(0.0, 0.6), (0.6, 0.8), (0.8, 0.9), (0.9, 1.01)]
    print("\n=== 置信度校准(B 臂) ===")
    print("置信度桶 | n | 平均置信 | 实际准确率")
    for lo, hi in buckets:
        cell = [r for r in rows if r["confidence"] >= 0 and lo <= r["confidence"] < hi]
        if not cell:
            continue
        # 校准口径从严:unsure(未判)一律不算"判对"
        acc = sum(1 for r in cell
                  if ALIAS.get(r["decision"], r["decision"]) == r["label"]) / len(cell)
        conf = sum(r["confidence"] for r in cell) / len(cell)
        print(f"[{lo:.1f},{hi if hi <= 1 else 1.0:.1f}) | {len(cell)} | {conf:.2f} | {acc:.2f}")


def main():
    arm = sys.argv[1] if len(sys.argv) > 1 else "all"
    gold = [r["label"] for r in LABELS]

    if arm in ("A", "all"):
        print("=== A 臂: 裸静态(全报) ===")
        print(compute_metrics(gold, ["bug"] * len(LABELS)))

    client = None
    if arm in ("B", "C", "all", "v2", "retr", "bi"):
        from cpp_sentinel.llm import llm_config
        base_url, _model, api_key = llm_config()
        if not api_key:
            raise SystemExit("请先设置: export CPP_SENTINEL_API_KEY=<你的key>(或 DEEPSEEK_API_KEY)")
        client = OpenAI(base_url=base_url, api_key=api_key)

    if arm in ("B", "all"):
        print("=== B 臂: +LLM(源码证据) ===")
        rows_b = run_arm(client, "llm", use_rag=False)
        print(compute_metrics(gold, [r["decision"] for r in rows_b]))
        calibration(rows_b)

    if arm in ("C", "all"):
        print("=== C 臂: +LLM+RAG ===")
        rows_c = run_arm(client, "llm_rag", use_rag=True)
        print(compute_metrics(gold, [r["decision"] for r in rows_c]))

    if arm == "v2":
        # 单变量对照:同子集同模型,只换 RUBRIC_V2(治"测试用例豁免"+check 语义错位)
        print("=== B 臂 v2 rubric 对照 ===")
        rows_b2 = run_arm(client, "llm_v2", use_rag=False, rubric=RUBRIC_V2)
        print(compute_metrics(gold, [r["decision"] for r in rows_b2]))
        print("=== C 臂 v2 rubric 对照 ===")
        rows_c2 = run_arm(client, "llm_rag_v2", use_rag=True, rubric=RUBRIC_V2)
        print(compute_metrics(gold, [r["decision"] for r in rows_c2]))

    if arm == "retr":
        # P6 检索方法消融:同语料同查询同 rubric,只换检索法(向量基线已存 juliet_arm_llm_rag)
        from cpp_sentinel.retrieval import Retriever
        print("=== C 臂检索消融: BM25(词面) ===")
        rows_bm = run_arm(client, "llm_rag_bm25", use_rag=True, retriever=Retriever("bm25"))
        print(compute_metrics(gold, [r["decision"] for r in rows_bm]))
        print("=== C 臂检索消融: 混合 RRF(向量+BM25) ===")
        rows_hy = run_arm(client, "llm_rag_hybrid", use_rag=True, retriever=Retriever("hybrid"))
        print(compute_metrics(gold, [r["decision"] for r in rows_hy]))

    if arm == "bi":
        # P7 双语语料:同判定集同 rubric,语料换 cwe_bi;三种检索法各跑一遍
        from cpp_sentinel.retrieval import Retriever
        for mode in ("vector", "bm25", "hybrid"):
            print(f"=== C 臂双语语料: {mode} ===")
            rows = run_arm(client, f"llm_rag_bi_{mode}", use_rag=True,
                           retriever=Retriever(mode, collection="cwe_bi"))
            print(compute_metrics(gold, [r["decision"] for r in rows]))


if __name__ == "__main__":
    main()
