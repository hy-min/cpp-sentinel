from pathlib import Path
import clang.cindex

SAMPLE = Path(__file__).parent / "fixtures" / "callers_sample.cpp"


def find_callers(filename: Path, target: str) -> set:
    idx = clang.cindex.Index.create()
    tu = idx.parse(str(filename), args=['-std=c++17', '-x', 'c++'])
    callers = set()

    def walk(node, func):
        for child in node.get_children():
            if child.kind == clang.cindex.CursorKind.DECL_REF_EXPR and child.spelling == target:
                if func is not None:
                    callers.add(func.spelling)
            f2 = func
            if child.kind in (clang.cindex.CursorKind.FUNCTION_DECL,
                              clang.cindex.CursorKind.CXX_METHOD):
                f2 = child
            walk(child, f2)

    walk(tu.cursor, None)
    return callers


def test_helper_callees():
    assert find_callers(SAMPLE, "helper") == {"caller1", "main"}


def test_main_callees():
    assert find_callers(SAMPLE, "caller1") == {"main"}
