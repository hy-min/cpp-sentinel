import json
from cpp_sentinel.models import Alert
from cpp_sentinel.review import Classification
from cpp_sentinel.report import ReviewResult, make_report, to_markdown, dump_all


def r(decision: str, conf: float) -> ReviewResult:
    return ReviewResult(
        alert=Alert(file="a.cc", line=1, col=2, severity="warning",
                    check_name="bugprone-x", message="m"),
        judgement=Classification(decision=decision, reason="r", confidence=conf),
    )


def test_make_report_counts_summary():
    rep = make_report([r("real", 0.9), r("suspicious", 0.6), r("ignore", 0.3)])
    assert rep["total"] == 3
    assert rep["summary"] == {"real": 1, "suspicious": 1, "ignore": 1}


def test_make_report_sorted_by_confidence():
    rep = make_report([r("ignore", 0.3), r("real", 0.9)])
    assert rep["entries"][0]["decision"] == "real"   # 0.9 的在前面


def test_markdown_contains_summary_and_all_labels():
    rep = make_report([r("real", 0.9), r("suspicious", 0.5), r("ignore", 0.2)])
    md = to_markdown(rep)
    assert "共 3 条告警" in md
    assert "真问题" in md and "疑似" in md and "忽略" in md


def test_dump_all_writes_json(tmp_path):
    path = tmp_path / "report.json"                        # 测试专用临时文件,跑完自动删
    dump_all([r("real", 0.9)], path=str(path))
    data = json.loads(path.read_text())
    assert data["entries"][0]["decision"] == "real"
