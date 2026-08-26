"""增量审查基元: git diff → 变更行区间 → 基线抑制(只留落在新代码上的告警)

真实代码审查的语义 = "只看这次改动引入的问题":
存量告警(历史债)不该淹没 PR 里新增的 3 条。
"""
import re
import subprocess
from pathlib import Path

from cpp_sentinel.models import Alert


def changed_lines(repo: str, base: str, dots: int = 3) -> dict[str, list[tuple[int, int]]]:
    """{相对路径: [(起,止)]} —— base 与 HEAD 之间的新增行区间(+ 侧,--unified=0)。

    dots=3: PR 场景(diff 相对 merge-base);dots=2: push 场景(diff 相对推送前 SHA)。
    """
    r = subprocess.run(["git", "diff", f"--unified=0", f"{base}{'.' * dots}HEAD", "--",
                        "*.cc", "*.cpp", "*.h", "*.hpp"],
                       capture_output=True, text=True, cwd=repo)
    if r.returncode != 0:
        raise RuntimeError(f"git diff 失败: {r.stderr.strip()[:200]}")
    out, cur = {}, None
    for line in r.stdout.splitlines():
        m = re.match(r"\+\+\+ b/(.+)", line)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", line)
        if m and cur:
            start = int(m.group(1))
            count = int(m.group(2) or "1")
            out.setdefault(cur, []).append((start, start + count - 1))
    return out


def filter_to_changed(alerts: list[Alert], changed: dict[str, list[tuple[int, int]]],
                      repo: str) -> list[Alert]:
    """基线抑制: 只保留告警行落在变更区间内的条目。"""
    keep = []
    for a in alerts:
        try:
            rel = str(Path(a.file).resolve().relative_to(Path(repo).resolve()))
        except ValueError:
            continue                          # 仓库外的告警(系统头等)不入审
        if any(lo <= a.line <= hi for lo, hi in changed.get(rel, [])):
            keep.append(a)
    return keep
