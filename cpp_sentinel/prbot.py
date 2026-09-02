"""PR 评论 bot: 把审查报告以 sticky 评论发到 PR(同一 PR 重复推送只更新同一条,不刷屏)。

sticky 机制: 评论体埋隐藏标记 <!-- cpp-sentinel-review -->;发之前列出该 PR 全部评论,
找到含标记的旧评论 → PATCH 更新,否则 POST 新建。

认证走 gh CLI(GitHub runner 预装): CI 里 env GH_TOKEN=${{ secrets.GITHUB_TOKEN }} 即可,
不需要额外 PAT;本地用已登录的 gh。评论走 issues API(PR 评论 = issue 评论),
workflow 需 permissions: issues: write。

用法:
    python -m cpp_sentinel.prbot --repo owner/name --pr 123 --body-file report.md
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from cpp_sentinel.report import LABEL_CN, PRICE_PER_1K

MARKER = "<!-- cpp-sentinel-review -->"
MAX_ENTRIES = 15          # 评论里最多列几条;全量留在 job Summary
MAX_BODY = 60000          # GitHub 评论上限 65536,留余量


def render_comment(report: dict, gate: bool = False) -> str:
    """报告 dict(make_report 产物)→ PR 评论 markdown(精简版,全量见 job Summary)。"""
    s = report["summary"]
    u = report["usage"]
    cost = (u["prompt_tokens"] / 1000) * PRICE_PER_1K["prompt"] + \
           (u["completion_tokens"] / 1000) * PRICE_PER_1K["completion"]
    lines = [
        MARKER,
        "## 🤖 cpp-sentinel 增量审查\n",
        f"共 {report['total']} 条新告警 — "
        f"真问题 {s['real']} / 疑似 {s['suspicious']} / 忽略 {s['ignore']} / 失败 {s['failed']}"
        f"(其中 {report['second_pass']} 条经二次判定)\n",
    ]
    entries = report["entries"]                       # 已按置信度降序(make_report)
    for e in entries[:MAX_ENTRIES]:
        lines.append(f"- [{LABEL_CN[e['decision']]}] `{e['file']}:{e['line']}` "
                     f"({e['check']}) 置信度 {e['confidence']:.2f} — {e['reason']}")
    if len(entries) > MAX_ENTRIES:
        lines.append(f"- ……其余 {len(entries) - MAX_ENTRIES} 条见 job Summary")
    for f in report["failed"][:3]:                    # 失败如实挂账,但最多 3 条
        lines.append(f"- [未能判定] `{f['file']}:{f['line']}` ({f['check']}) — ⚠ {f['error']}")
    lines.append(f"\n💰 本次消耗 {u['prompt_tokens']}+{u['completion_tokens']} tokens,"
                 f" 约 ¥{cost:.3f}")
    if gate:
        lines.append("\n🚪 门控模式: real 且置信度 ≥0.8 的告警会使本检查变红")
    return ("\n".join(lines) + "\n")[:MAX_BODY]


def render_empty(note: str) -> str:
    """无新告警/无 C++ 变更时的最小评论 —— 让 bot 在"干净 PR"上也有存在感(可观测性)。"""
    return f"{MARKER}\n## 🤖 cpp-sentinel 增量审查\n\n✅ {note}\n"


def _gh_api(*args: str) -> str:
    """gh api 薄封装: 失败抛异常让 CI 步骤可见地红,绝不静默吞掉。"""
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh api {args[0]} 失败: {r.stderr.strip()[:200]}")
    return r.stdout


def upsert_pr_comment(repo: str, pr: int, body: str) -> str:
    """找到含 MARKER 的旧评论则更新,否则新建。返回 "updated" / "created"。"""
    comments = json.loads(_gh_api(f"repos/{repo}/issues/{pr}/comments"))
    hit = next((c for c in comments if MARKER in (c.get("body") or "")), None)
    if hit:
        _gh_api(f"repos/{repo}/issues/comments/{hit['id']}", "-X", "PATCH", "-f", f"body={body}")
        return "updated"
    _gh_api(f"repos/{repo}/issues/{pr}/comments", "-f", f"body={body}")
    return "created"


def main() -> int:
    ap = argparse.ArgumentParser(description="cpp-sentinel PR 评论 bot(sticky)")
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--body-file", required=True)
    args = ap.parse_args()
    body = Path(args.body_file).read_text()
    state = upsert_pr_comment(args.repo, args.pr, body)
    print(f"PR #{args.pr} 评论已{'更新' if state == 'updated' else '创建'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
