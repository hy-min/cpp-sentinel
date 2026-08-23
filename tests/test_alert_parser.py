from pathlib import Path
from cpp_sentinel.models import Alert
from cpp_sentinel.parser import parse_alert

FIXTURES = Path(__file__).parent / "fixtures"

def test_parse_enum_size_warning():
    text = (FIXTURES / "warning_enum_size.txt").read_text()
    line = text.splitlines()[0]          # 现在只取第 1 行(主行)
    alert = parse_alert(line)
    assert alert.file.endswith("common/status.h")
    assert alert.line == 9
    assert alert.col == 12
    assert alert.severity == "warning"
    assert alert.check_name == "performance-enum-size"
    assert "ErrorCode" in alert.message