"""prbot 的测试 —— gh api 全 mock,不碰网络(同 test_retry.py 纪律)。"""
import json
import sys
from unittest.mock import MagicMock, patch

import pytest

import cpp_sentinel.ci as ci
from cpp_sentinel.prbot import (MARKER, render_comment, render_empty,
                                upsert_pr_comment)


def _report(n_entries: int = 2) -> dict:
    """手工造一个 make_report 同构的报告(避开 Alert/Classification 的构造噪音)。"""
    entries = [{"file": f"f{i}.cc", "line": i, "check": "bugprone-x",
                "decision": "real" if i % 2 else "ignore",
                "reason": f"理由{i}", "confidence": 0.9 - i * 0.01}
               for i in range(n_entries)]
    return {"total": n_entries,
            "summary": {"real": 1, "suspicious": 0, "ignore": n_entries - 1, "failed": 0},
            "entries": entries, "failed": [],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            "second_pass": 1}


def test_render_comment_has_marker_counts_and_cost():
    body = render_comment(_report(), gate=True)
    assert MARKER in body                          # sticky 机制的锚
    assert "真问题 1" in body and "忽略 1" in body
    assert "经二次判定" in body and "💰" in body    # 成本透明
    assert "门控模式" in body                       # gate 说明只在 --gate 时出现
    assert "门控模式" not in render_comment(_report(), gate=False)


def test_render_comment_caps_entries():
    body = render_comment(_report(20))
    assert "其余 5 条" in body                     # 评论精简,全量留 job Summary
    assert body.count("f1") <= 15                  # 截断生效


def test_render_empty_keeps_marker():
    body = render_empty("本次变更未引入新告警。")
    assert MARKER in body and "✅" in body and "未引入新告警" in body


def _gh_result(stdout: str, code: int = 0) -> MagicMock:
    return MagicMock(returncode=code, stdout=stdout, stderr="")


def test_upsert_creates_when_no_marker():
    """无旧评论 → POST 新建,返回 created。"""
    with patch("cpp_sentinel.prbot.subprocess.run") as m:
        m.side_effect = [_gh_result("[]"), _gh_result("{}")]
        assert upsert_pr_comment("o/r", 5, "body " + MARKER) == "created"
    post = m.call_args_list[1].args[0]
    assert post[:3] == ["gh", "api", "repos/o/r/issues/5/comments"]
    assert "PATCH" not in post


def test_upsert_updates_existing_marker():
    """旧评论含 marker → PATCH 原评论(sticky: 重复推送不刷屏)。"""
    old = json.dumps([{"id": 42, "body": "无关评论"},
                      {"id": 77, "body": f"旧版 {MARKER} 报告"}])
    with patch("cpp_sentinel.prbot.subprocess.run") as m:
        m.side_effect = [_gh_result(old), _gh_result("{}")]
        assert upsert_pr_comment("o/r", 5, "新 body") == "updated"
    patch_call = m.call_args_list[1].args[0]
    assert patch_call[:4] == ["gh", "api", "repos/o/r/issues/comments/77", "-X"]
    assert "PATCH" in patch_call


def test_upsert_raises_on_gh_failure():
    """gh 失败(权限/网络)→ 抛出让 CI 步骤红,不静默。"""
    with patch("cpp_sentinel.prbot.subprocess.run") as m:
        m.return_value = _gh_result("", code=1)
        m.return_value.stderr = "Forbidden"
        with pytest.raises(RuntimeError, match="Forbidden"):
            upsert_pr_comment("o/r", 5, "body")


def test_ci_out_md_written_when_no_cpp_changes(tmp_path, monkeypatch):
    """无 C++ 变更也要落盘 ✅ 评论载荷 —— 干净 PR 上 bot 有存在感。"""
    monkeypatch.setattr(ci, "changed_lines", lambda repo, base, dots=3: {})
    out = tmp_path / "review.md"
    monkeypatch.setattr(sys, "argv",
                        ["ci", "--repo", "/x", "--base", "main", "--out-md", str(out)])
    assert ci.main() == 0
    text = out.read_text()
    assert MARKER in text and "✅" in text
