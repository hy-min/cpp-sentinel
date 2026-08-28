"""多 Agent 角色(P9): triager(初筛) / fixer(修复建议)。

设计原则:reviewer 不做新实现——复用 eval/run_juliet.py 的 judge_one
(B 臂同 rubric 同证据),保证"单级 vs 多级"是可比的单变量对照。
triager 是**新增的便宜前级**:只看告警文本不看源码,高置信 ignore 才短路。
fixer 只在 real 判定后生成最小修复建议。
"""
from cpp_sentinel.cli import call_with_retry
from cpp_sentinel.review import parse_response

# 初筛:无源码证据、只看告警本身。宁可放过(交给 reviewer),不可错杀。
TRIAGE_RUBRIC = """你是 C++ 静态告警初筛员。只凭告警文本粗判(看不到源码):
- ignore: 明显是风格/可读性建议(如命名、unused、格式)
- suspicious: 拿不准(默认选项)
- real: 告警文本本身就描述明确内存/安全缺陷(如 null dereference、double free)
只输出 JSON: {"decision": "...", "reason": "一句话", "confidence": 0.x}"""

FIX_PROMPT = """你是 C++ 修复工程师。以下告警已被判定为真问题。给出最小修复补丁
(unified diff 或修复后的代码片段),并一句话说明修了什么。
告警: {alert}
相关源码:
{source}
只输出: ```diff 或 ```cpp 代码块 + 一句话说明。"""


def triage(client, row: dict):
    """初筛:只吃告警文本。返回 (Classification, usage)。"""
    alert = f"{row['file']}:{row['line']}: {row['check']}\n{row['message']}"
    text, _tries, usage = call_with_retry(
        client, [{"role": "user", "content": f"{TRIAGE_RUBRIC}\n\n=== 告警 ===\n{alert}"}])
    return parse_response(text), usage


def fix(client, row: dict, source: str):
    """修复建议:real 判定的告警 → 最小补丁。返回 (patch_text, usage)。"""
    alert = f"{row['file']}:{row['line']}: {row['check']}\n{row['message']}"
    text, _tries, usage = call_with_retry(
        client, [{"role": "user", "content": FIX_PROMPT.format(alert=alert, source=source)}])
    return text, usage
