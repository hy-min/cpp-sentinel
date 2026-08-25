"""cpp_sentinel CLI: 一条命令完成 6 站审查。

用法:
    python -m cpp_sentinel.cli           # 默认: dkvstore, LLM 判前 3 条
    python -m cpp_sentinel.cli --repo <path> --limit 19
"""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── R1 铁律:任何 LLM 库 import 之前清代理(见仓库 rules/environment.md)──
for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)

import openai                          # 异常类用 openai.XXX 前缀引用(与下行的 from 并存,不冲突)
from openai import OpenAI

from cpp_sentinel.callers import build_call_index, names_defined_in
from cpp_sentinel.models import Alert
from cpp_sentinel.parser import parse_alert                 # ★ 漏了这台"剪刀"(课1)
from cpp_sentinel.review import Classification, build_prompt, parse_response
from cpp_sentinel.report import ReviewResult, dump_all, make_report, to_markdown

SECOND_PASS_THRESHOLD = 0.8        # 信任线:低于它就"疑而不决 → 去查证"

TIDY_ARGS = ["--checks=bugprone-*,performance-*,clang-analyzer-*"]

RETRYABLE = {429, 500, 502, 503, 504}      # 服务器"临时不舒服"的错误码


def call_with_retry(client, messages: list, max_tries: int = 2,
                    backoff: float = 0.4) -> tuple[str, int, dict]:
    """调 LLM:临时故障最多重试(max_tries 次);返回 (文本, 尝试次数, token 账单);永久失败立刻抛出。"""
    last_err = None
    for attempt in range(1, max_tries + 1):
        try:
            resp = client.chat.completions.create(
                model="deepseek-chat", messages=messages, temperature=0)
            # ✅ 成功:带着用了几次 + 账单一起回去(usage 是 API 明账,不自己数)
            return (resp.choices[0].message.content, attempt,
                    {"prompt_tokens": resp.usage.prompt_tokens,
                     "completion_tokens": resp.usage.completion_tokens})
        except openai.APIConnectionError as e:                    # 网络断了——临时,值得重试
            last_err = e
        except openai.APITimeoutError as e:                       # 超时——临时,值得重试
            last_err = e
        except openai.APIStatusError as e:                        # 服务端回了(带状态码的)
            if e.status_code in RETRYABLE:
                last_err = e                                      # 429/5xx——临时,重试
            else:
                raise                                             # 401/402/400——永久,立刻放弃!
        if attempt < max_tries:
            print(f"      ⚠ 第 {attempt} 次失败({type(last_err).__name__}),{backoff:.1f}s 后重试 ...")
            time.sleep(backoff)                                   # 喘口气再试(别瞬时打爆服务器)
    raise last_err                                                # 试尽仍失败:如实上抛(降级是下一步)


def get_alert_lines(repo: str) -> list[str]:
    """① 工具链:跑 clang-tidy,拿回告警文本行。"""
    db = Path(repo) / "build" / "compile_commands.json"
    if not db.exists():
        raise SystemExit(f"找不到编译数据库 {db} —— 先: cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON")
    files = [e["file"] for e in json.loads(db.read_text())]        # 全部源文件(解除演示 [:3])
    lines = []
    for f in files:
        r = subprocess.run(["clang-tidy", "-p", str(Path(repo) / "build"), f, *TIDY_ARGS],
                           capture_output=True, text=True, cwd=repo)
        lines += r.stdout.splitlines()                     # 告警在 stdout;stderr 是统计摘要
    return lines


def parse_alerts(lines: list[str]) -> list[Alert]:
    """② 翻译:只留能解析成 Alert 的行;同一条告警在多个编译单元重复出现,按三元组去重。"""
    seen = set()                                        # 记"见过的三元组"的桶(集合)
    alerts = []
    for line in lines:
        try:
            a = parse_alert(line)                       # 课1 的"剪刀+校验"
        except ValueError:
            continue                                    # 摘要行/统计行,不是告警正文
        if (a.file, a.line, a.check_name) in seen:      # ① 文件+行+检查名 = 告警身份证
            continue                                    # ② 重复的:白判了,跳过(省钱!)
        seen.add((a.file, a.line, a.check_name))
        alerts.append(a)
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


def _merge_usage(u1: dict, u2: dict) -> dict:
    """两笔账单合并(两次判定 → 一条记录)。"""
    return {"prompt_tokens": u1["prompt_tokens"] + u2["prompt_tokens"],
            "completion_tokens": u1["completion_tokens"] + u2["completion_tokens"]}


def gather_evidence(alert: Alert, repo: str, index: dict[str, list[str]]) -> list[str]:
    """嫌疑名单(告警文件里定义的名字) ∩ 全库调用索引 = 使用侧证据。"""
    try:
        suspects = names_defined_in(Path(alert.file), repo)
    except Exception as e:                       # 宽网兜底:不崩,但必须出声(否则错误不可见)
        print(f"      (使用侧证据跳过: {e})")
        return []
    evidence = []
    for s in suspects:
        evidence.extend(index.get(s, []))
    return evidence[:6]                                 # 最多 6 条,撑爆 prompt 就是灾难


def judge_one(client, alert: Alert, repo: str, index: dict[str, list[str]]) -> ReviewResult:
    """单条判定:低置信度 → 带使用侧证据自动重判一次(最多一次,防死循环)。"""
    try:
        context = build_context(alert, repo)
        msg = [{"role": "user", "content": build_prompt(alert, context)}]
        text, _, usage = call_with_retry(client, msg)
        first = parse_response(text)
        if first.confidence >= SECOND_PASS_THRESHOLD:                # ① 高置信:一票定案
            return ReviewResult(alert=alert, judgement=first, usage=usage)
        evidence = gather_evidence(alert, repo, index)               # ② 敢不信:去查"谁在用"
        if not evidence:                                             # 查无证据:维持原判(诚实)
            return ReviewResult(alert=alert, judgement=first, usage=usage)
        prompt2 = build_prompt(alert, context) + (
            "\n=== 使用侧证据(这些地方调用了告警符号) ===\n" +
            "\n".join(evidence) +
            "\n注意:第一次判定因证据不足存疑;以上是调用点,若调用点在失败路径,应改判 real。")
        text2, _, usage2 = call_with_retry(client, [{"role": "user", "content": prompt2}])
        return ReviewResult(alert=alert, judgement=parse_response(text2),
                            usage=_merge_usage(usage, usage2), passes=2)     # ③ 二次判定为准
    except Exception as e:                                               # 兜底:任何意外都降级,绝不崩
        return ReviewResult(alert=alert, error=f"{type(e).__name__}: {e}")


def classify_all(alerts: list[Alert], repo: str, limit: int = 3, workers: int = 4) -> list[ReviewResult]:
    """⑤ LLM 判断:并发(workers 个"打饭窗口")补背景、交 DeepSeek,按原顺序回填。"""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("请先设置: export DEEPSEEK_API_KEY=<你的key>")
    client = OpenAI(base_url="https://api.deepseek.com/v1",
                    api_key=os.environ["DEEPSEEK_API_KEY"])

    t0 = time.perf_counter()                            # ② 计时器(秒表,比 time.time 更准)
    index = build_call_index(repo)                      # 只用一次:全库"谁在调用"索引(共享只读)
    print(f"      使用侧索引 {len(index)} 个函数")
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:        # ③ 开 workers 个窗口
        futures = {pool.submit(judge_one, client, a, repo, index): i
                   for i, a in enumerate(alerts[:limit])}
        for fut in as_completed(futures):               # ④ 挤到窗口的饭菜先上桌
            results.append((futures[fut], fut.result()))  # ⑤ (原来的第几号, 结果) 放一起
    results.sort(key=lambda x: x[0])                    # ⑥ 按号排回原顺序
    print(f"      ⏱ 并发 {workers} 路, {len(results)} 条判定, 用时 {time.perf_counter() - t0:.1f}s")
    return [r for _, r in results]


def run(repo: str = "/home/hy/dkvstore", limit: int = 3, workers: int = 4) -> list[ReviewResult]:
    """合龙:①→⑤ 串起来。"""
    lines = get_alert_lines(repo)
    alerts = parse_alerts(lines)
    print(f"clang-tidy 扫到 {len(alerts)} 条告警, LLM 判断前 {limit} 条 (workers={workers}) ...")
    return classify_all(alerts, repo, limit, workers=workers)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="cpp_sentinel CLI")
    ap.add_argument("repo", nargs="?", default="/home/hy/dkvstore")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)   # 1 = 串行(单窗口), 4 = 并发
    args = ap.parse_args()
    results = run(args.repo, args.limit, workers=args.workers)
    report = make_report(results)
    out_dir = Path(args.repo) / "out"
    out_dir.mkdir(exist_ok=True)
    dump_all(results, path=str(out_dir / "report.json"))
    (out_dir / "report.md").write_text(to_markdown(report))
    print(to_markdown(report))
    print(f"\n📄 报告已保存: {out_dir}/report.json + report.md")


if __name__ == "__main__":
    main()
