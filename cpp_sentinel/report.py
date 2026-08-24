import json
from dataclasses import dataclass
from typing import List

from cpp_sentinel.models import Alert
from cpp_sentinel.review import Classification

LABEL_CN = {"real": "真问题", "suspicious": "疑似", "ignore": "忽略"}


@dataclass
class ReviewResult:                       # ① 把"告警 + 判断"捆在一起的搬运箱
    alert: Alert
    judgement: Classification


def make_report(results: List[ReviewResult]) -> dict:
    counts = {"real": 0, "suspicious": 0, "ignore": 0}          # ② 三分类计数器
    for r in results:
        counts[r.judgement.decision] += 1
    entries = sorted(results,                                    # ③ 按置信度从高到低排
                     key=lambda r: r.judgement.confidence, reverse=True)
    return {
        "total": len(results),
        "summary": counts,                                       # ④ 三分类统计
        "entries": [                                             # ⑤ 每条:出处+判定+理由
            {
                "file": r.alert.file, "line": r.alert.line,
                "check": r.alert.check_name,
                "decision": r.judgement.decision,
                "reason": r.judgement.reason,
                "confidence": r.judgement.confidence,
            }
            for r in entries
        ],
    }


def to_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# 代码审查报告\n",
        f"共 {report['total']} 条告警 — "
        f"真问题 {s['real']} / 疑似 {s['suspicious']} / 忽略 {s['ignore']}\n",
    ]
    for e in report["entries"]:
        lines.append(
            f"- [{LABEL_CN[e['decision']]}] {e['file']}:{e['line']} "
            f"({e['check']}) 置信度 {e['confidence']:.2f} — {e['reason']}"
        )
    return "\n".join(lines) + "\n"


def dump_all(results: List[ReviewResult], path: str = "report.json") -> None:
    json.dump(make_report(results), open(path, "w"),               # ⑥ eval 原料仓
              ensure_ascii=False, indent=2)
