"""cpp_sentinel CLI: 一条命令完成 6 站审查。

用法:
    python -m cpp_sentinel.cli           # 默认: dkvstore, LLM 判前 3 条
    python -m cpp_sentinel.cli --repo <path> --limit 19
"""
import json
import os
import subprocess
import sys
from pathlib import Path

# ── R1 铁律:任何 LLM 库 import 之前清代理(见仓库 rules/environment.md)──
for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)

from openai import OpenAI

from cpp_sentinel.models import Alert
from cpp_sentinel.parser import parse_alert                 # ★ 漏了这台"剪刀"(课1)
from cpp_sentinel.review import Classification, parse_response
from cpp_sentinel.report import ReviewResult, dump_all, make_report, to_markdown

TIDY_ARGS = ["--checks=bugprone-*,performance-*,clang-analyzer-*"]


def get_alert_lines(repo: str) -> list[str]:
    """① 工具链:跑 clang-tidy,拿回告警文本行。"""
    db = Path(repo) / "build" / "compile_commands.json"
    if not db.exists():
        raise SystemExit(f"找不到编译数据库 {db} —— 先: cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON")
    files = [e["file"] for e in json.loads(db.read_text())][:3]     # 演示取前 3 个源文件
    lines = []
    for f in files:
        r = subprocess.run(["clang-tidy", "-p", str(Path(repo) / "build"), f, *TIDY_ARGS],
                           capture_output=True, text=True, cwd=repo)
        lines += r.stdout.splitlines()                     # 告警在 stdout;stderr 是统计摘要
    return lines


def parse_alerts(lines: list[str]) -> list[Alert]:
    """② 翻译:只留能解析成 Alert 的行(其余噪音跳过)。"""
    alerts = []
    for line in lines:
        try:
            alerts.append(parse_alert(line))           # 课1 的"剪刀+校验"
        except ValueError:
            pass                                        # 摘要行/统计行,不是告警正文
    return alerts


def build_context(alert: Alert, repo: str) -> str:
    """③④ 背景:调用计数(课2 减化版) + 知识库命中(课3)。"""
    ctx = []
    # ③ 背景A:库内 TOP 被调函数(用 compile_commands 定位该源文件)
    try:
        import clang.cindex
        idx = clang.cindex.Index.create()
        src = Path(alert.file)
        if src.suffix in (".h", ".hpp"):
            tu = idx.parse(str(src), args=["-std=c++17", "-I" + str(Path(repo) / "include"), "-x", "c++"])
        else:
            tu = idx.parse(str(src), args=["-std=c++17", "-I" + str(Path(repo) / "include")])
        from collections import Counter
        called = Counter()
        for node in tu.cursor.walk_preorder():
            if node.kind == clang.cindex.CursorKind.CALL_EXPR:
                f = node.location.file
                if f is not None and str(f).startswith(repo):
                    called[node.spelling] += 1
        ctx.append("该文件范围内高频调用: " +
                   ", ".join(f"{n}×{c}" for n, c in called.most_common(5)))
    except Exception as e:
        ctx.append(f"(符号分析跳过: {e})")
    # ④ 背景B:知识库检索(CWE 命中)
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(Path(repo) / "data" / "chroma"))
        col = client.get_or_create_collection("cwe")
        hit = col.query(query_texts=[alert.message], n_results=1)
        if hit["ids"][0]:
            ctx.append("相关规范: " + hit["metadatas"][0][0]["title"])
    except Exception as e:
        ctx.append(f"(知识库跳过: {e})")
    return "; ".join(ctx)


def classify_all(alerts: list[Alert], repo: str, limit: int = 3) -> list[ReviewResult]:
    """⑤ LLM 判断:每两条补背景,交 DeepSeek,回填判断。"""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("请先设置: export DEEPSEEK_API_KEY=<你的key>")
    client = OpenAI(base_url="https://api.deepseek.com/v1",
                    api_key=os.environ["DEEPSEEK_API_KEY"])
    from cpp_sentinel.review import build_prompt
    results = []
    for alert in alerts[:limit]:
        context = build_context(alert, repo)
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": build_prompt(alert, context)}],
            temperature=0)
        judgement = parse_response(resp.choices[0].message.content)
        results.append(ReviewResult(alert=alert, judgement=judgement))
    return results


def run(repo: str = "/home/hy/dkvstore", limit: int = 3) -> list[ReviewResult]:
    """合龙:①→⑤ 串起来。"""
    lines = get_alert_lines(repo)
    alerts = parse_alerts(lines)
    print(f"clang-tidy 扫到 {len(alerts)} 条告警, LLM 判断前 {limit} 条 ...")
    return classify_all(alerts, repo, limit)


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else "/home/hy/dkvstore"
    results = run(repo)
    report = make_report(results)
    out_dir = Path(repo) / "out"
    out_dir.mkdir(exist_ok=True)
    dump_all(results, path=str(out_dir / "report.json"))
    (out_dir / "report.md").write_text(to_markdown(report))
    print(to_markdown(report))
    print(f"\n📄 报告已保存: {out_dir}/report.json + report.md")


if __name__ == "__main__":
    main()
