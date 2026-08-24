"""挑告警池:全量扫目标仓库,去重,落盘 eval/dataset/alerts.jsonl
用法: python dump_alerts.py <repo> [max_files]  (TIDY_EXTRA_INCLUDE 可补隐式 include)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # 认祖:把项目根加入导入路径

from cpp_sentinel.parser import parse_alert

repo = sys.argv[1] if len(sys.argv) > 1 else "/home/hy/dkvstore"
max_files = int(sys.argv[2]) if len(sys.argv) > 2 else None   # 可选:只扫前 N 个文件(大仓库用)

db = json.loads((Path(repo) / "build" / "compile_commands.json").read_text())
files = [e["file"] for e in db][:max_files]      # 编译清单里(可截断)的源文件

seen = set()                                     # 去重用的"指纹集"
out = []

for f in files:
    extra_inc = os.environ.get("TIDY_EXTRA_INCLUDE", "")
    cmd = ["clang-tidy", "-p", "build", f,
           "--checks=bugprone-*,performance-*,clang-analyzer-*"]
    if extra_inc:
        # 用 -isystem:第三方头按"系统头"对待,其告警会被 clang-tidy 抑制
        cmd.append("--extra-arg=-isystem")
        cmd.append(f"--extra-arg={extra_inc}")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=repo)
    for line in r.stdout.splitlines():           # 告警在 stdout(课6 流的教训!)
        try:
            a = parse_alert(line)                # 课1 剪刀
        except ValueError:
            continue                             # 摘要行跳过
        key = (a.file, a.line, a.check_name)     # 去重三要素:文件+行+检查名
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "file": a.file, "line": a.line, "col": a.col,
            "severity": a.severity, "check": a.check_name,
            "message": a.message,
        })

Path("eval/dataset").mkdir(parents=True, exist_ok=True)
Path("eval/dataset/alerts.jsonl").write_text(
    "\n".join(json.dumps(o, ensure_ascii=False) for o in out))
print(f"共 {len(out)} 条去重告警 → eval/dataset/alerts.jsonl")
