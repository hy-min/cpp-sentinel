from dataclasses import dataclass

@dataclass
class Alert:
    file: str          # 文件路径,如 /home/hy/dkvstore/include/.../status.h
    line: int          # 行号,如 9
    col: int           # 列号,如 12
    severity: str      # "warning" / "error"
    check_name: str    # "performance-enum-size"
    message: str       # 完整告警描述