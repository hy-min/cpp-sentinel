import json
from dataclasses import dataclass
from typing import List

from cpp_sentinel.llm import llm_config
from cpp_sentinel.models import Alert
from cpp_sentinel.review import Classification

LABEL_CN = {"real": "真问题", "suspicious": "疑似", "ignore": "忽略", "failed": "未能判定"}

# 单价(元/千 tokens)——DeepSeek 口径;以官方计费页为准
PRICE_PER_1K = {"prompt": 0.002, "completion": 0.008}


def cost_cny(prompt_tokens: int, completion_tokens: int) -> float | None:
    """已知单价的模型返回 ¥ 估计;未知模型(如 GLM)返回 None —— 不打误导性价格。"""
    if llm_config()[1].startswith("deepseek"):
        return (prompt_tokens / 1000) * PRICE_PER_1K["prompt"] + \
               (completion_tokens / 1000) * PRICE_PER_1K["completion"]
    return None


@dataclass
class ReviewResult:                       # ① 把"告警 + 判断"捆在一起的搬运箱
    alert: Alert
    judgement: Classification | None = None    # 判定成功才有;失败时是 None
    error: str | None = None                   # 失败时的人话原因
    usage: dict | None = None                  # 本判定消耗的 token 账单(API 明账)
    passes: int = 1                            # 判定了几次(2 = 走了一次二次判定)


def make_report(results: List[ReviewResult]) -> dict:
    counts = {"real": 0, "suspicious": 0, "ignore": 0, "failed": 0}     # 四态计数器
    failed = []
    judged = []
    for r in results:
        if r.judgement is None:                                  # 降级项单独挂账
            counts["failed"] += 1
            failed.append({"file": r.alert.file, "line": r.alert.line,
                           "check": r.alert.check_name, "error": r.error})
        else:
            counts[r.judgement.decision] += 1
            judged.append(r)
    entries = sorted(judged,                                     # ③ 成功的按置信度排
                     key=lambda r: r.judgement.confidence, reverse=True)
    pt = sum(r.usage["prompt_tokens"] for r in results if r.usage)          # ④ 账单主线程汇总
    ct = sum(r.usage["completion_tokens"] for r in results if r.usage)
    second_pass = sum(1 for r in results if r.passes == 2)                  # ⑤ 走二判的条目数
    return {
        "total": len(results),
        "summary": counts,                                       # ④ 四态统计
        "entries": [                                             # ⑤ 成功判定明细
            {
                "file": r.alert.file, "line": r.alert.line,
                "check": r.alert.check_name,
                "decision": r.judgement.decision,
                "reason": r.judgement.reason,
                "confidence": r.judgement.confidence,
            }
            for r in entries
        ],
        "failed": failed,                                        # ⑥ 失败明细:诚实挂账
        "usage": {"prompt_tokens": pt, "completion_tokens": ct},  # ⑦ 账单汇总(顶层,不混进判定)
        "second_pass": second_pass,                               # ⑧ 二判条目数(可观测性)
    }


def to_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# 代码审查报告\n",
        f"共 {report['total']} 条告警 — "
        f"真问题 {s['real']} / 疑似 {s['suspicious']} / 忽略 {s['ignore']} / 失败 {s['failed']}"
        f"(其中 {report['second_pass']} 条经二次判定)\n",
    ]
    for e in report["entries"]:
        lines.append(
            f"- [{LABEL_CN[e['decision']]}] {e['file']}:{e['line']} "
            f"({e['check']}) 置信度 {e['confidence']:.2f} — {e['reason']}"
        )
    for f in report["failed"]:
        lines.append(f"- [未能判定] {f['file']}:{f['line']} ({f['check']}) — ⚠ {f['error']}")
    u = report["usage"]
    cost = cost_cny(u["prompt_tokens"], u["completion_tokens"])
    if cost is None:
        lines.append(f"\n💰 本次消耗 {u['prompt_tokens']}+{u['completion_tokens']} tokens"
                     f"({llm_config()[1]} 计费以模型方账单为准)")
    else:
        lines.append(f"\n💰 本次消耗 {u['prompt_tokens']}+{u['completion_tokens']} tokens, 约 ¥{cost:.3f}")
    return "\n".join(lines) + "\n"


def dump_all(results: List[ReviewResult], path: str = "report.json") -> None:
    json.dump(make_report(results), open(path, "w"),               # ⑥ eval 原料仓
              ensure_ascii=False, indent=2)
