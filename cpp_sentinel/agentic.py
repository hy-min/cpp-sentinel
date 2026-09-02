"""工具调用 Agent(P10): LLM 自主拉证据的判定循环。

与 B 臂(eval/run_juliet.py 的 judge_one)的唯一差异 = 证据获取方式:
  B 臂: 启发式预取(短文件全文 / 长文件 ±25 行窗口) → 一次 LLM 调用
  P10 : 同 rubric 同模型,LLM 用 tools 按需拉证据,多轮循环,最多 max_rounds 次调用
判定 rubric 的判定标准 / 输出 schema / 解析器(parse_response)/ 评分(compute_metrics)
与 B 臂逐字一致 —— 单变量对照,回答"Agent 编排是否优于固定 workflow"。

工具结果统一截断(MAX_TOOL_CHARS)并记 trace —— trace 落盘后可回答
"LLM 到底拉了什么、拉几次",这是 P10 的副产物数据。
"""
import json
import os
import time
from pathlib import Path

# ── R1 铁律:任何 LLM 库 import 之前清代理 ──
for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)

import openai

from cpp_sentinel.callers import names_defined_in
from cpp_sentinel.cli import RETRYABLE                    # 重试策略单源(课14)
from cpp_sentinel.llm import llm_config, reasoning_effort  # provider 可换(DeepSeek/GLM/…)
from cpp_sentinel.review import parse_response

MAX_TOOL_CHARS = 4000         # 单条工具结果上限: 防爆 prompt,也逼 LLM 用 span 精准取证
FULL_FILE_MAX_LINES = 400


def source_snippet(file: str, line: int, span: int = 25) -> str:
    """与 run_juliet.source_snippet 同逻辑(短文件全文 / 长文件 ±span 窗口)。
    拷贝入包而非 import eval 脚本: run_juliet 保持不动,历史基线才可复现。"""
    p = Path(file)
    if not p.exists():
        return "(源文件不可读)"
    lines = p.read_text(errors="ignore").splitlines()
    if len(lines) <= 120:
        return "\n".join(f"{i+1}: {lines[i]}" for i in range(len(lines)))
    lo, hi = max(0, line - span), min(len(lines), line + span)
    return "\n".join(f"{i+1}: {lines[i]}" for i in range(lo, hi))


def _chat(client, messages: list, tools: list | None = None,
          max_tries: int = 3, backoff: float = 0.8):
    """call_with_retry 的 tools 版(重试策略同款,次数/间隔放宽: agentic 调用量大,
    429 更常见,多给一次机会)。返回 (message, usage) 对象。"""
    last_err = None
    for attempt in range(1, max_tries + 1):
        try:
            kw = {"model": llm_config()[1], "messages": messages, "temperature": 0}
            if effort := reasoning_effort():                # GLM-5 系: low/high/max
                kw["extra_body"] = {"reasoning_effort": effort}
            if tools:
                kw["tools"] = tools
            resp = client.chat.completions.create(**kw)
            return resp.choices[0].message, resp.usage
        except openai.APIConnectionError as e:            # 网络断 —— 临时,重试
            last_err = e
        except openai.APITimeoutError as e:               # 超时 —— 临时,重试
            last_err = e
        except openai.APIStatusError as e:                # 服务端带状态码
            if e.status_code in RETRYABLE:
                last_err = e                              # 429/5xx —— 临时,重试
            else:
                raise                                     # 401/402/400 —— 永久,立刻放弃
        if attempt < max_tries:
            print(f"      ⚠ 第 {attempt} 次失败({type(last_err).__name__}),{backoff:.1f}s 后重试 ...")
            time.sleep(backoff)
    raise last_err


class ToolBox:
    """一条告警的取证工具集: 文件默认值绑定告警文件;结果统一截断 + 记 trace。"""

    def __init__(self, row: dict, retriever=None):
        self.row = row
        self.file = row["file"]
        self.retriever = retriever                        # None = T-lite 臂(无 KB)
        self.trace: list[dict] = []
        self.tool_chars = 0

    def get_snippet(self, line: int = 0, span: int = 25, file: str = "") -> str:
        return source_snippet(file or self.file,
                              int(line or self.row["line"]), int(span or 25))

    def get_full_file(self, file: str = "") -> str:
        p = Path(file or self.file)
        if not p.exists():
            return "(源文件不可读)"
        lines = p.read_text(errors="ignore").splitlines()
        cut = lines[:FULL_FILE_MAX_LINES]
        out = "\n".join(f"{i+1}: {l}" for i, l in enumerate(cut))
        if len(lines) > FULL_FILE_MAX_LINES:
            out += f"\n...(截断: 仅前 {FULL_FILE_MAX_LINES}/{len(lines)} 行)"
        return out

    def list_defined_names(self, file: str = "") -> str:
        f = file or self.file
        names = names_defined_in(Path(f), str(Path(f).parent))
        return "文件内定义的符号: " + (", ".join(sorted(names)) if names else "(无)")

    def get_callers(self, name: str = "", file: str = "") -> str:
        """文本级(非 AST): Juliet 用例单文件自包含,跨文件调用图无意义,如实文件内查找。"""
        p = Path(file or self.file)
        if not p.exists():
            return "(源文件不可读)"
        hits = []
        for i, l in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            if f"{name}(" in l:
                hits.append(f"{i}: {l.strip()[:110]}")
            if len(hits) >= 8:
                break
        return ("调用/出现点:\n" + "\n".join(hits)) if hits else f"(文件内无 {name}( 出现)"

    def search_kb(self, query: str = "") -> str:
        if self.retriever is None:
            return "(知识库未启用 —— 本臂不提供)"
        title, doc, dbg = self.retriever.query(query)
        return f"相关规范: {title}\n{doc[:600]}" if title else f"(无命中, {dbg})"

    def dispatch(self, name: str, args: dict) -> str:
        """工具分发: 未知工具/参数错误都回错误串,绝不崩(LLM 乱调不能炸掉整条判定)。"""
        fn = {"get_snippet": self.get_snippet, "get_full_file": self.get_full_file,
              "list_defined_names": self.list_defined_names,
              "get_callers": self.get_callers,
              "search_kb": self.search_kb}.get(name)
        if fn is None:
            out = f"(未知工具: {name})"
        else:
            try:
                out = fn(**(args or {}))
            except Exception as e:
                out = f"(工具失败: {type(e).__name__}: {e})"
        if len(out) > MAX_TOOL_CHARS:
            out = out[:MAX_TOOL_CHARS] + "\n...(截断)"
        self.trace.append({"tool": name, "args": args, "chars": len(out)})
        self.tool_chars += len(out)
        return out


def _spec(name: str, desc: str, props: dict, required: list) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required}}}


_FILE = {"file": {"type": "string", "description": "文件路径,省略 = 告警文件"}}

TOOLS_FULL = [
    _spec("get_snippet", "取源码片段: 某行 ±span 行(带行号)。最常用,先取告警行附近。",
          {"line": {"type": "integer", "description": "中心行号"},
           "span": {"type": "integer", "description": "半径行数,默认 25"}, **_FILE},
          ["line"]),
    _spec("get_full_file", f"取文件全文(带行号,超 {FULL_FILE_MAX_LINES} 行截断)。",
          {**_FILE}, []),
    _spec("list_defined_names", "列出文件内定义的函数/类符号(AST 级,libclang)。",
          {**_FILE}, []),
    _spec("get_callers", "在文件内查找某符号的调用/出现行(文本级,最多 8 条)。",
          {"name": {"type": "string", "description": "符号名"}, **_FILE}, ["name"]),
    _spec("search_kb", "检索 CWE 知识库,返回最相关条款(标题 + 摘要)。",
          {"query": {"type": "string", "description": "查询文本,英文告警信息亦可"}}, ["query"]),
]
TOOLS_NOKB = [t for t in TOOLS_FULL if t["function"]["name"] != "search_kb"]

AGENTIC_ADDENDUM = """=== 证据收集方式(重要) ===
你没有现成背景: 先用工具自行收集证据(源码片段/全文/符号/调用点/知识库),
充分后立即判定;避免重复或漫无目的的调用,通常 1-3 次取证足够。"""


def agentic_rubric(base: str) -> str:
    """rubric 单点插入(与 RUBRIC_V2 同 idiom): 判定标准逐字不动,只加取证方式说明。"""
    return base.replace("只输出 JSON", AGENTIC_ADDENDUM + "\n只输出 JSON")


def agentic_judge(client, row: dict, toolbox: ToolBox, tools: list,
                  rubric: str, max_rounds: int = 6) -> dict:
    """单条告警的 agentic 判定: 工具循环 → 最终 JSON。乱答记 unsure(与 judge_one 同口径)。"""
    alert = f"{row['file']}:{row['line']}: {row['check']}\n{row['message']}"
    messages = [{"role": "user", "content": f"{rubric}\n\n=== 告警 ===\n{alert}"}]
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    final_text = ""
    rounds = 0
    for r in range(max_rounds):
        last = (r == max_rounds - 1)
        if last:                                   # 强制收敛: 摘掉工具,只许给判定
            messages.append({"role": "user",
                             "content": "证据收集到此为止,立即输出 JSON 判定。"})
        msg, u = _chat(client, messages, tools=None if last else tools)
        usage["prompt_tokens"] += u.prompt_tokens
        usage["completion_tokens"] += u.completion_tokens
        rounds += 1
        if not getattr(msg, "tool_calls", None):
            final_text = msg.content or ""
            break
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": tc.id, "type": "function",
                                         "function": {"name": tc.function.name,
                                                      "arguments": tc.function.arguments}}
                                        for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}                          # 参数乱答: 交给工具层报错,不崩
            out = toolbox.dispatch(tc.function.name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
    result = {"usage": usage, "rounds": rounds,
              "tool_trace": toolbox.trace, "tool_chars": toolbox.tool_chars}
    try:
        c = parse_response(final_text)
        return {**result, "decision": c.decision,
                "confidence": c.confidence, "reason": c.reason}
    except Exception as e:
        return {**result, "decision": "unsure", "confidence": -1,
                "reason": f"解析失败: {type(e).__name__}: {e}"}
