"""agentic 判定循环的测试 —— 全 mock,不打 API(同 test_retry.py 纪律)。

关键坑: MagicMock 对未显式设置的属性会编幽灵值 —— message.tool_calls 必须
显式给(None 或成型的列表),否则循环会把"没调工具"误判成"还要调工具"。
"""
import json
from unittest.mock import MagicMock

from cpp_sentinel.agentic import (MAX_TOOL_CHARS, TOOLS_FULL, TOOLS_NOKB,
                                  ToolBox, agentic_judge, agentic_rubric)

ROW = {"file": "x.cpp", "line": 10, "check": "c", "message": "m",
       "label": "bug", "cwe": "CWE000"}
FINAL = '{"decision": "real", "reason": "证据充分", "confidence": 0.9}'


def _tc(name: str, args: dict, tid: str = "t1"):
    """伪造一次工具调用请求(id/function.name/function.arguments 显式成型)。"""
    tc = MagicMock()
    tc.id = tid
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _resp(content=None, tool_calls=None, pt: int = 10, ct: int = 5):
    r = MagicMock()
    r.choices = [MagicMock(message=MagicMock(content=content, tool_calls=tool_calls))]
    r.usage = MagicMock(prompt_tokens=pt, completion_tokens=ct)
    return r


def _client(script: list):
    """按剧本依次返回;记录每次调用的 kwargs 供断言。"""
    c = MagicMock()
    c.calls_kw = []

    def _create(**kw):
        c.calls_kw.append(kw)
        return script[len(c.calls_kw) - 1]

    c.chat.completions.create.side_effect = _create
    return c


def test_happy_path_two_rounds():
    """先拉证据再给判定: 2 轮,usage 逐轮累加,tool 结果回填进下一轮 messages。"""
    row = {**ROW, "file": __file__}                      # 用本文件当真文件,snippet 必有内容
    client = _client([_resp(tool_calls=[_tc("get_snippet", {"line": 1, "span": 5})]),
                      _resp(content=FINAL)])
    r = agentic_judge(client, row, ToolBox(row), TOOLS_FULL, "RUBRIC", max_rounds=6)
    assert r["decision"] == "real" and r["rounds"] == 2
    assert r["usage"] == {"prompt_tokens": 20, "completion_tokens": 10}   # 两笔账合并
    assert [t["tool"] for t in r["tool_trace"]] == ["get_snippet"]
    sent = client.calls_kw[1]["messages"]                # 第 2 轮看到的对话
    assert sent[-2]["role"] == "assistant" and sent[-2]["tool_calls"][0]["id"] == "t1"
    assert sent[-1] == {"role": "tool", "tool_call_id": "t1",
                        "content": sent[-1]["content"]}
    assert "1:" in sent[-1]["content"]                   # 真 snippet 进去了


def test_direct_answer_one_round():
    """模型不调工具直接判定 → 1 轮收工,trace 为空。"""
    client = _client([_resp(content=FINAL)])
    r = agentic_judge(client, ROW, ToolBox(ROW), TOOLS_FULL, "R")
    assert r["rounds"] == 1 and r["decision"] == "real" and r["tool_trace"] == []


def test_forced_convergence_at_max_rounds():
    """工具瘾患者: 每轮都要工具 → 最后一轮摘掉 tools 强制判定。"""
    script = [_resp(tool_calls=[_tc("get_snippet", {"line": 1})]) for _ in range(2)]
    script.append(_resp(content=FINAL, pt=99))
    client = _client(script)
    r = agentic_judge(client, ROW, ToolBox(ROW), TOOLS_FULL, "R", max_rounds=3)
    assert client.chat.completions.create.call_count == 3
    assert "tools" not in client.calls_kw[2]             # 最后一轮无工具可调
    assert "立即输出 JSON" in client.calls_kw[2]["messages"][-1]["content"]
    assert r["rounds"] == 3 and r["decision"] == "real"
    assert r["usage"]["prompt_tokens"] == 10 + 10 + 99


def test_unparseable_final_becomes_unsure():
    """最终回话不是 JSON → unsure/-1,usage/轮数如实保留(与 judge_one 同口径)。"""
    client = _client([_resp(content="我觉得吧……这不是 JSON")])
    r = agentic_judge(client, ROW, ToolBox(ROW), TOOLS_FULL, "R")
    assert r["decision"] == "unsure" and r["confidence"] == -1
    assert "解析失败" in r["reason"] and r["usage"]["prompt_tokens"] == 10


def test_dispatch_unknown_tool_and_bad_args():
    """LLM 乱调(不存在的工具/错误参数类型)→ 错误串回喂,不崩,trace 照记。"""
    tb = ToolBox(ROW)
    assert "未知工具" in tb.dispatch("nope", {})
    assert "工具失败" in tb.dispatch("get_snippet", {"line": "abc"})
    assert len(tb.trace) == 2 and tb.trace[0]["tool"] == "nope"


def test_get_callers_text_level(tmp_path):
    f = tmp_path / "a.cpp"
    f.write_text("void foo() {}\nint main() {\n  foo();\n}\n")
    tb = ToolBox({**ROW, "file": str(f)})
    out = tb.get_callers("foo")
    assert "1: void foo() {}" in out and "3: foo();" in out
    assert "无 bar(" in tb.get_callers("bar")


def test_tool_result_truncation(tmp_path):
    f = tmp_path / "big.cpp"
    f.write_text("\n".join(f"line {i} " + "x" * 100 for i in range(100)))   # ≫ MAX_TOOL_CHARS
    tb = ToolBox({**ROW, "file": str(f)})
    out = tb.dispatch("get_full_file", {})
    assert "截断" in out[-12:] and len(out) <= MAX_TOOL_CHARS + 12


def test_list_defined_names(tmp_path):
    f = tmp_path / "b.cpp"
    f.write_text("int helper() { return 1; }\nint main() { return helper(); }\n")
    out = ToolBox({**ROW, "file": str(f)}).dispatch("list_defined_names", {})
    assert "helper" in out and "main" in out


def test_tlite_excludes_kb():
    names = [t["function"]["name"] for t in TOOLS_NOKB]
    assert "search_kb" not in names and len(names) == len(TOOLS_FULL) - 1
    assert "未启用" in ToolBox(ROW, retriever=None).dispatch("search_kb", {"query": "x"})


def test_agentic_rubric_inserts_without_touching_schema():
    """rubric 只加取证方式一节,判定标准与输出 schema 逐字不动(单变量纪律)。"""
    base = "判定标准 AAA\n只输出 JSON: {}"
    out = agentic_rubric(base)
    assert "AAA" in out and "证据收集方式" in out and out.endswith("只输出 JSON: {}")


def test_resume_skips_successful_rows(tmp_path, monkeypatch):
    """断点续跑(402 事故教训): 已有结果里 usage 非空的行不重跑,失败行自动补。"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
    import run_agentic as RA
    monkeypatch.setattr(RA, "RESULTS", tmp_path)

    rows = [{**ROW, "file": __file__, "line": 10 + i, "label": "bug"} for i in range(3)]
    seed_ok = {**rows[0], "decision": "real", "confidence": 0.9, "reason": "旧结果",
               "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "rounds": 1,
               "tool_trace": [], "tool_chars": 0}
    seed_bad = {**rows[1], "decision": "unsure", "confidence": -1, "reason": "402",
                "usage": {}, "rounds": 0, "tool_trace": [], "tool_chars": 0}
    (tmp_path / "juliet_arm_pytest.jsonl").write_text(
        json.dumps(seed_ok) + "\n" + json.dumps(seed_bad) + "\n")

    client = _client([_resp(content=FINAL)] * 3)
    out = RA.run_arm(client, "pytest", TOOLS_NOKB, None, rows, 6, 2)
    assert client.chat.completions.create.call_count == 2     # 只补跑失败行 + 新行
    assert out[0]["reason"] == "旧结果"                        # 成功行原样保留
    assert out[1]["decision"] == "real" and out[2]["decision"] == "real"
    assert [r["line"] for r in out] == [10, 11, 12]            # 顺序与判定集一致
