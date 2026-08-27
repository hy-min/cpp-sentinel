"""运行时观测(P8): 进程内指标注册表 + Prometheus 文本导出。

零依赖手写(不引 prometheus_client):计数器 + 延迟采样 + token/成本账单,
渲染 Prometheus text exposition format——可直接被 Prometheus/Grafana 抓取,
也可肉眼 curl /metrics 查看。
"""
import threading
from collections import defaultdict

_LOCK = threading.Lock()
_COUNTERS = defaultdict(float)                    # (name, label) → 累计值
_LATENCY = []                                     # 近 1000 次 review 耗时(秒)

_BUCKETS = (1, 5, 10, 30, 60, 120, 300)           # review 耗时分桶(秒)
PRICE_PER_1K = {"prompt": 0.002, "completion": 0.008}   # 与 report.py 同价目


def inc(name: str, by: float = 1.0, label: str = "") -> None:
    with _LOCK:
        _COUNTERS[(name, label)] += by


def record_review(results, duration_s: float) -> None:
    """一次审查的全部记账:请求数/告警数/判定分布/二判数/token/成本/耗时。"""
    n = len(results)
    inc("cpp_sentinel_reviews_total")
    inc("cpp_sentinel_alerts_judged_total", n)
    for r in results:
        decision = r.judgement.decision if r.judgement else "failed"
        inc("cpp_sentinel_decisions_total", 1, decision)
        if r.passes == 2:
            inc("cpp_sentinel_second_pass_total")
    pt = sum(r.usage.get("prompt_tokens", 0) for r in results if r.usage)
    ct = sum(r.usage.get("completion_tokens", 0) for r in results if r.usage)
    inc("cpp_sentinel_tokens_total", pt, "prompt")
    inc("cpp_sentinel_tokens_total", ct, "completion")
    cost = pt / 1000 * PRICE_PER_1K["prompt"] + ct / 1000 * PRICE_PER_1K["completion"]
    inc("cpp_sentinel_cost_yuan_total", cost)
    with _LOCK:
        _LATENCY.append(duration_s)
        del _LATENCY[:-1000]                      # 只留最近 1000 次


def render() -> str:
    """Prometheus text exposition format。"""
    lines = []
    with _LOCK:
        for (name, label), v in sorted(_COUNTERS.items()):
            if label:
                lines.append(f'{name}{{kind="{label}"}} {v:g}')
            else:
                lines.append(f"{name} {v:g}")
        lat = list(_LATENCY)
    # 延迟直方图(累计桶)
    for b in _BUCKETS:
        lines.append(
            f'cpp_sentinel_review_duration_seconds_bucket{{le="{b:g}"}} '
            f"{sum(1 for x in lat if x <= b)}")
    lines.append('cpp_sentinel_review_duration_seconds_bucket{le="+Inf"} '
                 f"{len(lat)}")
    lines.append(f"cpp_sentinel_review_duration_seconds_sum {sum(lat):g}")
    lines.append(f"cpp_sentinel_review_duration_seconds_count {len(lat)}")
    return "\n".join(lines) + "\n"


def _reset() -> None:                             # 测试用:清零
    with _LOCK:
        _COUNTERS.clear()
        _LATENCY.clear()
