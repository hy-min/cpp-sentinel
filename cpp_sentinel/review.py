from typing import Literal
from pydantic import BaseModel, Field
from cpp_sentinel.models import Alert            # ① 借课 1 的"告警表格"

class Classification(BaseModel):                 # ② 判断的"答卷模板"——只能三种判法
    decision: Literal["real", "suspicious", "ignore"]
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)

RUBRIC = """你是 C++ 静态审查助手。针对告警与上下文,判定:
- real: 证据充分(如:被广泛调用、路径可达、符合 CWE)→ 真问题
- suspicious: 证据不足,值得人工再看
- ignore: 误报/风格问题
只输出 JSON: {"decision": "...", "reason": "一句话理由", "confidence": 0.x}"""

def build_prompt(alert: Alert, context: str) -> str:
    return (
        f"{RUBRIC}\n\n=== 告警 ===\n"
        f"{alert.file}:{alert.line}: {alert.check_name}\n{alert.message}\n"
        f"=== 背景 ===\n{context}\n"
    )

def parse_response(text: str) -> Classification:
    start = text.find("{")                       # ③ 用"剪刀"从 LLM 回话里剪出 JSON
    end = text.rfind("}") + 1
    return Classification.model_validate_json(text[start:end])   # ④ 按模板校验 + 实例化
