"""cpp_sentinel CI 驱动: 增量扫描 + 基线抑制 + LLM 判定 + Markdown 报告

用法:
    python -m cpp_sentinel.ci --repo <path> --base <ref> [--dots 3] [--gate] [--workers 8]

前置: repo 下有 build/compile_commands.json(cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON,
只需 configure 不需构建)。退出码: 默认 0(建议模式); --gate 时存在高置信 real → 1。
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)                                     # R1 铁律

from cpp_sentinel.cli import classify_all, parse_alerts         # 复用并发判定/去重
from cpp_sentinel.incremental import changed_lines, filter_to_changed
from cpp_sentinel.prbot import render_comment, render_empty     # PR 评论载荷(带 sticky 标记)
from cpp_sentinel.report import make_report, to_markdown

TIDY_ARGS = ["--checks=bugprone-*,performance-*,clang-analyzer-*"]
GATE_CONFIDENCE = 0.8           # 门控模式: real 且置信 ≥0.8 才挂 PR


def scan_files(repo: str, files: list[str]) -> list[str]:
    """clang-tidy 扫变更文件(用 repo/build 的编译数据库)。"""
    lines = []
    for f in files:
        r = subprocess.run(["clang-tidy", "-p", str(Path(repo) / "build"), f, *TIDY_ARGS],
                           capture_output=True, text=True, cwd=repo)
        lines += r.stdout.splitlines()
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description="cpp_sentinel CI 增量审查")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True, help="PR: base.sha;push: event.before")
    ap.add_argument("--dots", type=int, default=3, choices=[2, 3])
    ap.add_argument("--gate", action="store_true", help="高置信 real 时退出码 1")
    ap.add_argument("--out-md", default="",
                    help="PR 评论载荷落盘路径(含 sticky 标记,供 prbot 步骤读取)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    changed = changed_lines(args.repo, args.base, dots=args.dots)
    if not changed:
        print("无 C++ 变更,跳过审查。")
        if args.out_md:                             # 干净 PR 也要有评论(bot 存在感的证据)
            Path(args.out_md).write_text(render_empty("本次变更不涉及 C++ 代码。"))
        return 0
    files = [str(Path(args.repo) / rel) for rel in changed]
    alerts = parse_alerts(scan_files(args.repo, files))
    new_alerts = filter_to_changed(alerts, changed, args.repo)
    print(f"变更文件 {len(files)} → 静态告警 {len(alerts)} → 基线抑制后 {len(new_alerts)} 条入审")
    if not new_alerts:
        print("变更未引入新告警。")
        if args.out_md:
            Path(args.out_md).write_text(render_empty("本次变更未引入新告警。"))
        return 0

    results = classify_all(new_alerts, args.repo, limit=len(new_alerts), workers=args.workers)
    for r in results:                               # 显示层: 报告/评论用仓库相对路径(CI 绝对路径又长又丑)
        try:
            r.alert.file = str(Path(r.alert.file).resolve().relative_to(Path(args.repo).resolve()))
        except ValueError:
            pass
    report = make_report(results)
    md = to_markdown(report)
    print(md)
    if args.out_md:                                 # 评论载荷: 精简版,须在 gate 退出前落盘
        Path(args.out_md).write_text(render_comment(report, gate=args.gate))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:                                     # CI 里顺手写进 job 页面
        with open(summary, "a") as fh:
            fh.write(md + "\n")

    n_real = sum(1 for r in results
                 if r.judgement and r.judgement.decision == "real"
                 and r.judgement.confidence >= GATE_CONFIDENCE)
    if args.gate and n_real:
        print(f"🚫 门控: {n_real} 条高置信 real(≥{GATE_CONFIDENCE})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
