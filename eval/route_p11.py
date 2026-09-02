"""P11 check 族路由: B 臂单判 / T 臂 agentic 按 check 语义分流 —— 零 LLM 成本分析

两臂判定都已存盘(P4 基线 + P10),路由臂 = 每行取其中一臂的判定,token 同理按臂求和。
两个口径,严格区分:
  1. 语义规则(先验): 判定依赖告警行之外数据流的 check → agentic,其余 → B 单判。
     依据 check 语义,不依据结果倒推。
  2. oracle 上限(事后): 每个 check 选 F1 更高的臂 —— 拟合本集,只作天花板参考,
     不可作为结论引用。

用法: python eval/route_p11.py   (纯数据分析,不打 LLM)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))    # 认祖

from cpp_sentinel.metrics import compute_metrics

RESULTS = Path(__file__).resolve().parent / "results"

# 语义规则(先验): 正确性依赖"值从哪来/到哪去"的数据流 check → agentic。
# 纯风格(双臂本来就同判)与 analyzer 内存族(B 已 ≥0.93,留给单判)→ B。
AGENTIC_PREFIX = ("bugprone-unchecked", "bugprone-suspicious-realloc-usage")


def load(name: str) -> dict:
    rows = [json.loads(l) for l in (RESULTS / f"{name}.jsonl").read_text().splitlines()]
    return {(r["file"], r["line"], r["check"]): r for r in rows}


def tokens_of(rows: dict, keys: list) -> int:
    return sum(r["usage"].get("prompt_tokens", 0) + r["usage"].get("completion_tokens", 0)
               for k in keys if (r := rows.get(k)) and r.get("usage"))


def route(b: dict, t: dict, keys: list, prefix=AGENTIC_PREFIX) -> dict:
    """逐行分流: check 命中前缀 → T 臂判定+账单,否则 → B 臂。"""
    gold, pred, toks, n_agentic = [], [], 0, 0
    for k in keys:
        use_t = k[2].startswith(prefix)
        src = t if use_t else b
        toks += (src[k]["usage"].get("prompt_tokens", 0) +
                 src[k]["usage"].get("completion_tokens", 0)) if src[k].get("usage") else 0
        n_agentic += use_t
        gold.append(b[k]["label"])
        pred.append(src[k]["decision"])
    return {**compute_metrics(gold, pred), "token": toks, "agentic_rows": n_agentic}


def main():
    B, T, TL = load("juliet_arm_llm"), load("juliet_arm_agentic"), load("juliet_arm_agentic_nokb")
    keys = [k for k in B if k in T and k in TL]
    print(f"共同键 {len(keys)} 条")

    base = compute_metrics([B[k]["label"] for k in keys], [B[k]["decision"] for k in keys])
    bt = tokens_of(B, keys)
    print(f"B 臂(全单判)   : {base}, token {bt:,}")

    for name, t in (("T", T), ("T-lite", TL)):
        r = route(B, t, keys)
        print(f"路由 B+{name:<6}: {r}  (agentic 行 {r['agentic_rows']}, "
              f"token {r['token']:,} = B 的 {r['token']/bt:.2f}×)")

    # oracle 上限(事后拟合,仅天花板): 每 check 选 F1 更优臂
    checks = {k[2] for k in keys}
    gold, pred = [], []
    for c in checks:
        ks = [k for k in keys if k[2] == c]
        g = [B[k]["label"] for k in ks]
        fb = compute_metrics(g, [B[k]["decision"] for k in ks])["f1"]
        ft = compute_metrics(g, [T[k]["decision"] for k in ks])["f1"]
        pick = T if ft > fb else B
        gold += g
        pred += [pick[k]["decision"] for k in ks]
    print(f"oracle 上限(B/T 逐 check 择优,事后): {compute_metrics(gold, pred)}")


if __name__ == "__main__":
    main()
