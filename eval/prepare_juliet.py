"""Juliet 基准接入: clang-tidy 扫描 4 CWE 子集 → 告警解析 → 函数级真值标签 → 分层采样落盘

真值口径（Juliet 套件自身约定）: 函数名含 "bad" 的函数体 = 缺陷区域(bug),
其余(good*/main/文件作用域) = 正常代码(noise)。粒度 = 函数级,如实记录在报告。

用法: conda run -n cpp-review python eval/prepare_juliet.py [--scan-limit N]
产物: eval/dataset/alerts_juliet.jsonl(全量池) + labels_juliet.jsonl(LLM 判定子集)
"""
import json
import random
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))    # 认祖

from cpp_sentinel.parser import parse_alert

JULIET = Path("/home/hy/datasets/juliet")
SUPPORT = JULIET / "C" / "testcasesupport"
CWES = ["CWE476_NULL_Pointer_Dereference", "CWE401_Memory_Leak",
        "CWE369_Divide_by_Zero", "CWE415_Double_Free"]
CHECKS = "--checks=bugprone-*,performance-*,clang-analyzer-*"   # 与 dkvstore 同一检查组
OUT = Path(__file__).resolve().parent / "dataset"

SAMPLE_PER_CWE_LABEL = 60      # 每个 (CWE × 标签) 格子最多取 60 条进 LLM 判定集
SEED = 42


def iter_files():
    for cwe in CWES:
        for f in sorted((JULIET / "C" / "testcases" / cwe).rglob("*.cpp")):   # 大 CWE 有 s01/ 子目录
            yield f


def scan_one(f: Path) -> list[str]:
    """clang-tidy 扫单文件(自包含,无需 compile_commands)。"""
    r = subprocess.run(["clang-tidy", str(f), CHECKS, "--",
                        "-I", str(SUPPORT), "-std=c++14"],
                       capture_output=True, text=True, timeout=120)
    return r.stdout.splitlines()


FLAW_RE = re.compile(r"/\*\s*(POTENTIAL\s+)?FLAW", re.IGNORECASE)   # Juliet 缺陷行官方标记
FLAW_WINDOW = 4                     # 告警落在 FLAW 注释行后 4 行内 → 认定命中缺陷语句


def flaw_lines(f: Path) -> list[int]:
    """该文件中所有 /* FLAW */ / /* POTENTIAL FLAW */ 注释所在行号。"""
    return [i + 1 for i, ln in enumerate(f.read_text(errors="ignore").splitlines())
            if FLAW_RE.search(ln)]


def bad_ranges(f: Path) -> list[tuple[int, int]]:
    """libclang 求该文件内名字含 bad 的函数定义行区间 = 缺陷区域。"""
    import clang.cindex
    idx = clang.cindex.Index.create()
    tu = idx.parse(str(f), args=["-std=c++14", "-I", str(SUPPORT), "-x", "c++"])
    ranges = []
    for n in tu.cursor.walk_preorder():
        if n.is_definition() and "bad" in (n.spelling or ""):
            loc = n.location.file
            if loc is not None and Path(str(loc)).resolve() == f:   # 只认本文件定义
                ranges.append((n.extent.start.line, n.extent.end.line))
    return ranges


def main():
    scan_limit = 0
    if "--scan-limit" in sys.argv:
        i = sys.argv.index("--scan-limit")
        scan_limit = int(sys.argv[i + 1])
    # 随机子抽样(复现种子),而非截头部:各 CWE 的缺陷模式分布才不变
    rng = random.Random(SEED)
    files = list(iter_files())
    if scan_limit:
        files = sorted(rng.sample(files, min(scan_limit, len(files))))
    print(f"扫描 {len(files)} 个 Juliet 用例文件 ...")

    # ① 并发扫描
    with ThreadPoolExecutor(max_workers=16) as pool:
        all_lines = list(pool.map(scan_one, files))

    # ② 解析 + 只保留指向用例文件自身的告警(丢弃 testcasesupport/系统头里的)
    file_set = {f for f in files}
    seen, alerts = set(), []
    for f, lines in zip(files, all_lines):
        for ln in lines:
            try:
                a = parse_alert(ln)
            except ValueError:
                continue
            ap = Path(a.file)
            if not ap.is_absolute():
                ap = (Path.cwd() / ap).resolve()
            if ap != f:                                  # 告警落点在别的文件:不算本用例
                continue
            key = (str(f), a.line, a.check_name)
            if key in seen:
                continue
            seen.add(key)
            alerts.append(a)
    print(f"解析得告警 {len(alerts)} 条(已去重、已限本文件)")

    # ③ 行级真值标签(修 P4-1 口径事故:函数级位置标签把 bad() 内的风格告警也算 bug,
    #    与 LLM 语义判定系统性冲突 → B 臂召回假性 0.17):
    #    bug ⟺ 在 bad 函数体内 且 告警行距 FLAW 注释行 ≤4 行(落在缺陷语句上);
    #    clang-diagnostic-* 是编译器固有病啸,剔除不计
    bad_cache, flaw_cache = {}, {}
    rows = []
    for a in alerts:
        f = Path(a.file)
        if f not in bad_cache:
            bad_cache[f] = bad_ranges(f)
            flaw_cache[f] = flaw_lines(f)
        in_bad = any(lo <= a.line <= hi for lo, hi in bad_cache[f])
        on_flaw = any(0 <= a.line - fl <= FLAW_WINDOW for fl in flaw_cache[f])
        cwe = f.relative_to(JULIET / "C" / "testcases").parts[0]   # s01/ 子目录时归宗到 CWE
        rows.append({"file": str(f), "line": a.line, "check": a.check_name,
                     "message": a.message, "cwe": cwe,
                     "label": "bug" if (in_bad and on_flaw) else "noise"})
    n_diag = sum(1 for r in rows if r["check"].startswith("clang-diagnostic-"))
    rows = [r for r in rows if not r["check"].startswith("clang-diagnostic-")]
    print(f"剔除 clang-diagnostic-* 病啸 {n_diag} 条(编译器固有,非判定对象)")
    stats = Counter((r["cwe"], r["label"]) for r in rows)
    print("全量池分布:")
    for cwe in CWES:
        b, n = stats.get((cwe, "bug"), 0), stats.get((cwe, "noise"), 0)
        print(f"  {cwe}: bug={b} noise={n}  (noise 占比 {n/(b+n)*100:.0f}%)" if b+n else f"  {cwe}: 无告警")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "alerts_juliet.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")

    # ④ 分层采样(CWE × 标签,每格 ≤60) → LLM 判定子集
    subset = []
    for cwe in CWES:
        for label in ("bug", "noise"):
            cell = [r for r in rows if r["cwe"] == cwe and r["label"] == label]
            rng.shuffle(cell)
            subset.extend(cell[:SAMPLE_PER_CWE_LABEL])
    rng.shuffle(subset)
    (OUT / "labels_juliet.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in subset) + "\n")
    sub_stats = Counter(r["label"] for r in subset)
    print(f"判定子集 {len(subset)} 条: bug={sub_stats['bug']} noise={sub_stats['noise']} (seed={SEED})")


if __name__ == "__main__":
    main()
