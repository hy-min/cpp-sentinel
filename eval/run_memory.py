"""P12 反馈记忆消融(GLM): B-GLM 基线 / M1-full 全量历史记忆 / M1-corr 仅纠正记忆

单变量: 是否注入历史人工复核 few-shot。判定集/rubric(v1)/温度/评分全同。
口径纪律:
- 历史 H / 评测 E 按 (cwe,label) 分层对半分(seed 42);记忆只来自 H,E 行永不入库;
- 检索 exclude_key 防自检索;渲染不含文件路径;
- 历史 B 臂数字是 DeepSeek 跑的,本实验全部 GLM(glm-5.3-flash)——不与历史混比,
  B-GLM 全量重跑同时兼作"头条指标跨模型稳健性"数据点。

用法:
  export CPP_SENTINEL_API_KEY=<glm key>
  export CPP_SENTINEL_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
  export CPP_SENTINEL_MODEL=glm-5.3-flash
  python eval/run_memory.py [--arm B|M|all]

产物: eval/results/juliet_arm_llm_glm.jsonl / mem_full_glm.jsonl / mem_corr_glm.jsonl
"""
import argparse
import json
import os
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))    # 认祖

for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)                                     # R1 铁律

from openai import OpenAI

import run_juliet as RJ                                        # 同磅秤单源
from cpp_sentinel.llm import llm_config
from cpp_sentinel.memory import MemoryStore
from cpp_sentinel.metrics import compute_metrics

RESULTS = RJ.RESULTS
RJ.WORKERS = 4                       # GLM 免费档限流保守一点(重试兜不住会落 unsure)
WORKERS = 4
ALIAS = {"real": "bug", "ignore": "noise", "suspicious": "unsure"}


def split_history_eval(rows: list[dict], seed: int = 42) -> tuple[list, list]:
    """按 (cwe,label) 分层,组内稳定排序后 shuffle,奇偶交替 → H/E 各约一半。"""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["cwe"], r["label"])].append(r)
    rng = random.Random(seed)
    H, E = [], []
    for g in groups.values():
        g = sorted(g, key=lambda r: (r["file"], r["line"]))
        rng.shuffle(g)
        H += g[::2]
        E += g[1::2]
    return H, E


def key(r: dict) -> tuple:
    return (r["file"], r["line"], r["check"])


def run_rows(client, name: str, rows: list, store: MemoryStore | None) -> list[dict]:
    """E 集判定: store=None 即纯 B 臂;否则每行注入记忆 few-shot。"""
    t0 = time.perf_counter()
    out = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {}
        for i, r in enumerate(rows):
            hint = ""
            if store is not None:
                hint = MemoryStore.render(store.similar(
                    r["check"], r["message"], exclude_key=key(r)))
            futs[pool.submit(RJ.judge_one, client, r, False, RJ.RUBRIC, None, hint)] = i
        for fut in as_completed(futs):
            out.append((futs[fut], fut.result()))
            print(f"  {name}: {len(out)}/{len(rows)}", end="\r")
    out.sort(key=lambda x: x[0])
    rows_out = [r for _, r in out]
    tokens = sum(r["usage"].get("prompt_tokens", 0) + r["usage"].get("completion_tokens", 0)
                 for r in rows_out if r["usage"])
    print(f"\n  {name} 完成: {len(rows_out)} 条, {time.perf_counter()-t0:.0f}s, token {tokens:,}")
    (RESULTS / f"juliet_arm_{name}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows_out) + "\n")
    return rows_out


def show(name: str, rows: list[dict]) -> None:
    m = compute_metrics([r["label"] for r in rows], [r["decision"] for r in rows])
    unsure = sum(1 for r in rows if r["decision"] == "unsure")
    tokens = sum(r["usage"].get("prompt_tokens", 0) + r["usage"].get("completion_tokens", 0)
                 for r in rows if r["usage"])
    print(f"  [{name}] {m}" + (f"  ⚠unsure {unsure}" if unsure else "") +
          f", token {tokens:,}")


def main():
    ap = argparse.ArgumentParser(description="P12 反馈记忆消融")
    ap.add_argument("--arm", choices=["B", "M", "all"], default="all")
    args = ap.parse_args()

    H, E = split_history_eval(RJ.LABELS)
    bugs_h = sum(1 for r in H if r["label"] == "bug")
    bugs_e = sum(1 for r in E if r["label"] == "bug")
    print(f"划分: H {len(H)}(bug {bugs_h}) / E {len(E)}(bug {bugs_e})")

    base_url, model, api_key = llm_config()
    if not api_key:
        raise SystemExit("请先设置: export CPP_SENTINEL_API_KEY=<你的key>")
    print(f"模型: {model} @ {base_url}")
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=120)   # 防挂死

    b_path = RESULTS / "juliet_arm_llm_glm.jsonl"
    if args.arm in ("B", "all") or not b_path.exists():
        print("=== B-GLM 基线(全量 451,兼跨模型稳健性对照) ===")
        RJ.run_arm(client, "llm_glm", use_rag=False)

    if args.arm in ("M", "all"):
        b_all = {key(r): r for r in
                 (json.loads(l) for l in b_path.read_text().splitlines())}
        b_e = [b_all[key(r)] for r in E if key(r) in b_all]
        print("=== B-GLM 在 E 子集(基线同口径) ===")
        show("B-GLM@E", b_e)

        # M1-full: H 全量人工结论入库(bot 当时判定一并记录,供校准)
        full = MemoryStore(RESULTS / "memory_h_full.jsonl")
        full.entries = []
        for r in H:
            br = b_all.get(key(r))
            full.add(check=r["check"], message=r["message"], human_label=r["label"],
                     bot_decision=br["decision"] if br else "", file=r["file"], line=r["line"])
        full.save()
        print(f"=== M1-full(H 全量 {len(full.entries)} 条入库),评 E ===")
        show("M1-full@E", run_rows(client, "mem_full_glm", E, full))

        # M1-corr: 仅 B-GLM 在 H 上判错/拿不准的行入库(生产上更现实的策展)
        corr = MemoryStore(RESULTS / "memory_h_corr.jsonl")
        corr.entries = []
        for r in H:
            br = b_all.get(key(r))
            if br and ALIAS.get(br["decision"], br["decision"]) != r["label"]:
                corr.add(check=r["check"], message=r["message"], human_label=r["label"],
                         bot_decision=br["decision"], file=r["file"], line=r["line"])
        corr.save()
        print(f"=== M1-corr(仅纠正 {len(corr.entries)} 条入库),评 E ===")
        show("M1-corr@E", run_rows(client, "mem_corr_glm", E, corr))


if __name__ == "__main__":
    main()
