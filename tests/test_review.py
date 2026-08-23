import pytest
from cpp_sentinel.models import Alert
from cpp_sentinel.review import Classification, build_prompt, parse_response


def alert_on_enum() -> Alert:
    return Alert(
        file="/home/hy/dkvstore/include/dkvstore/common/status.h",
        line=9,
        col=12,
        severity="warning",
        check_name="performance-enum-size",
        message="enum 'ErrorCode' uses a larger base type than necessary",
    )


def test_parse_valid_json():
    raw = '{"decision": "real", "reason": "被 300 个调用点使用", "confidence": 0.9}'
    c = parse_response(raw)
    assert c.decision == "real"
    assert c.confidence == 0.9


def test_prompt_contains_alert_and_context():
    p = build_prompt(alert_on_enum(), "背景:被 3 个函数调用")
    assert "status.h" in p
    assert "背景:被 3 个函数调用" in p


def test_bad_decision_rejected():
    raw = '{"decision": "maybe", "reason": "x", "confidence": 0.5}'
    with pytest.raises(ValueError):
        parse_response(raw)


def test_confidence_out_of_range_rejected():
    raw = '{"decision": "ignore", "reason": "风格问题", "confidence": 1.5}'
    with pytest.raises(ValueError):
        parse_response(raw)
