"""反馈记忆 MemoryStore 的测试 —— 检索纪律(同 check 优先/防自检索/不泄路径)是重点。"""
import json

from cpp_sentinel.memory import MemoryStore


def _store(tmp_path, entries):
    s = MemoryStore(tmp_path / "mem.jsonl")
    for e in entries:
        s.add(**e)
    return s


def test_same_check_priority(tmp_path):
    """同 check 优先: 即使别的 check 词面更像,也先给同 check 的历史结论。"""
    s = _store(tmp_path, [
        {"check": "bugprone-a", "message": "totally different words", "human_label": "noise"},
        {"check": "bugprone-b", "message": "null pointer dereference here", "human_label": "bug"},
    ])
    hit = s.similar("bugprone-a", "null pointer dereference", k=1)
    assert [h["check"] for h in hit] == ["bugprone-a"]


def test_bm25_ranks_within_same_check(tmp_path):
    """同 check 候选超 k → BM25 把词面更相似的排前。"""
    s = _store(tmp_path, [
        {"check": "c", "message": "apple banana cherry", "human_label": "noise"},
        {"check": "c", "message": "null pointer dereference", "human_label": "bug"},
        {"check": "c", "message": "orange grape melon", "human_label": "noise"},
    ])
    hit = s.similar("c", "null pointer", k=1)
    assert hit[0]["message"] == "null pointer dereference"


def test_exclude_key_prevents_self_retrieval(tmp_path):
    """评测纪律: 正在判的行绝不能检索到自己(泄漏防护)。"""
    s = _store(tmp_path, [
        {"check": "c", "message": "m", "human_label": "bug", "file": "a.cc", "line": 5},
    ])
    assert s.similar("c", "m", exclude_key=("a.cc", 5, "c")) == []
    assert len(s.similar("c", "m", exclude_key=("other.cc", 9, "c"))) == 1


def test_render_hides_file_path(tmp_path):
    """渲染不含文件路径(路径含 CWE 名 → 标签泄漏)。"""
    s = _store(tmp_path, [
        {"check": "c", "message": "m", "human_label": "bug",
         "bot_decision": "ignore", "file": "/x/CWE476_NULL_Pointer/a.cc", "line": 1},
    ])
    out = s.render(s.entries)
    assert "历史人工复核" in out and "真问题" in out
    assert "bot 当时判 ignore" in out
    assert "CWE476" not in out and "/x/" not in out


def test_persistence_roundtrip(tmp_path):
    s = _store(tmp_path, [{"check": "c", "message": "m", "human_label": "bug"}])
    s.save()
    s2 = MemoryStore(tmp_path / "mem.jsonl")
    assert len(s2.entries) == 1 and s2.entries[0]["human_label"] == "bug"


def test_judge_one_injects_memory(monkeypatch):
    """ci 判定路径: memory 命中时 prompt 里出现历史复核段(全 mock,不打 LLM)。"""
    from unittest.mock import MagicMock

    import cpp_sentinel.cli as cli
    from cpp_sentinel.models import Alert

    monkeypatch.setattr(cli, "build_context", lambda alert, repo: "CTX")
    mem = MemoryStore("/nonexistent.jsonl")
    mem.add(check="c", message="m", human_label="bug", bot_decision="ignore")
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(
        content='{"decision": "real", "reason": "r", "confidence": 0.9}'))]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    client.chat.completions.create.return_value = resp
    r = cli.judge_one(client, Alert(file="x.h", line=1, col=1, severity="warning",
                                    check_name="c", message="m"), "/tmp/nope", {}, memory=mem)
    sent = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "历史人工复核" in sent and "真问题" in sent
    assert r.judgement.decision == "real"
