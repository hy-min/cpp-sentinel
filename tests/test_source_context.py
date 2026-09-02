"""生产链路源码证据的测试(dogfood 实跑抓出的缺口: build_context 此前不带源码)。"""
import sys

import cpp_sentinel.cli as cli
from cpp_sentinel.models import Alert


def _alert(line: int, file: str) -> Alert:
    return Alert(file=file, line=line, col=1, severity="warning",
                 check_name="clang-analyzer-core.NullDereference", message="m")


def test_source_context_window(tmp_path):
    """±span 窗口: 含告警行、带行号、上下各 span 行。"""
    f = tmp_path / "a.cc"
    f.write_text("\n".join(f"line{i}" for i in range(1, 41)))
    out = cli._source_context(_alert(20, str(f)), span=5)
    assert "20: line20" in out
    assert out.startswith("15: line15") and "25: line25" in out
    assert "14:" not in out and "26:" not in out


def test_source_context_missing_file():
    assert cli._source_context(_alert(1, "/no/such.cc")) == "(源文件不可读)"


def test_build_context_leads_with_source(tmp_path, monkeypatch):
    """build_context 第一段必须是源码证据;chroma 缺席时降级不崩(知识库跳过)。"""
    monkeypatch.setitem(sys.modules, "chromadb", None)   # import 即失败 → 走降级分支
    f = tmp_path / "a.cc"
    f.write_text("int main() {\n  int* p = nullptr;\n  return *p;\n}\n")
    out = cli.build_context(_alert(3, str(f)), str(tmp_path))
    assert out.startswith("=== 告警源码 ===")
    assert "3:   return *p;" in out
    assert "知识库跳过" in out                            # 降级可见,不静默
