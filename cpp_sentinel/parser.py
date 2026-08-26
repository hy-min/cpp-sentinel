import re
from cpp_sentinel.models import Alert

PATTERN = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+): "
    r"(?P<severity>warning|error): (?P<msg>.*) \[(?P<check>[\w.-]+)\]$"
)   # check 名必须含点号:clang-analyzer-core.NullDereference 这类带点检查曾被静默丢弃(P4-2)


def parse_alert(line: str) -> Alert:
    """把 clang-tidy 告警主行解析成 Alert。"""
    m = PATTERN.match(line)
    if m is None:
        raise ValueError(f"无法解析: {line}")
    return Alert(
        file=m.group("path"),
        line=int(m.group("line")),
        col=int(m.group("col")),
        severity=m.group("severity"),
        check_name=m.group("check"),
        message=m.group("msg"),
    )