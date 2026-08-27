"""P8 观测层测试: 注册表渲染 + API 端点(mock 掉管线,不打 LLM)。"""
import json

from fastapi.testclient import TestClient

from cpp_sentinel import observe
from cpp_sentinel.api import app
from cpp_sentinel.models import Alert
from cpp_sentinel.report import ReviewResult
from cpp_sentinel.review import Classification


def _rr(decision="real", passes=1, pt=100, ct=10):
    a = Alert(file="x.cc", line=1, col=1, severity="warning",
              check_name="bugprone-x", message="m")
    j = Classification(decision=decision, reason="r", confidence=0.9)
    return ReviewResult(alert=a, judgement=j,
                        usage={"prompt_tokens": pt, "completion_tokens": ct},
                        passes=passes)


def test_record_review_counters():
    observe._reset()
    observe.record_review([_rr("real"), _rr("ignore", passes=2)], 2.5)
    out = observe.render()
    assert "cpp_sentinel_reviews_total 1" in out
    assert "cpp_sentinel_alerts_judged_total 2" in out
    assert 'cpp_sentinel_decisions_total{kind="real"} 1' in out
    assert 'cpp_sentinel_decisions_total{kind="ignore"} 1' in out
    assert "cpp_sentinel_second_pass_total 1" in out
    assert 'cpp_sentinel_tokens_total{kind="prompt"} 200' in out
    assert "cpp_sentinel_review_duration_seconds_count 1" in out
    # 成本: 200*0.002/1000*1000... = 200/1000*0.002 + 20/1000*0.008
    assert "cpp_sentinel_cost_yuan_total" in out


def test_histogram_buckets():
    observe._reset()
    observe.record_review([_rr()], 2.5)
    out = observe.render()
    assert 'le="5"' in out                       # 2.5s 落进 le=5 桶
    assert 'le="1"' in out


def test_api_metrics_endpoint(tmp_path, monkeypatch):
    observe._reset()
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "compile_commands.json").write_text("[]")
    monkeypatch.setattr("cpp_sentinel.api.run",
                        lambda repo, limit, workers: [_rr("ignore")])
    c = TestClient(app)
    r = c.post("/api/review", json={"repo": str(tmp_path), "limit": 1})
    assert r.status_code == 200
    m = c.get("/metrics")
    assert m.status_code == 200
    assert "cpp_sentinel_reviews_total 1" in m.text
    h = c.get("/healthz")
    assert h.json() == {"ok": True}


def test_api_repo_without_compile_db(tmp_path, monkeypatch):
    monkeypatch.setattr("cpp_sentinel.api.run", lambda *a, **k: [])
    c = TestClient(app)
    r = c.post("/api/review", json={"repo": str(tmp_path), "limit": 1})
    assert r.status_code == 400                 # 无编译数据库 → 400,不崩
