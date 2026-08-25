"""使用侧证据(课17):从一个 C++ 仓库的 AST 里提取"谁在调用告警符号",供二次判定。

核心思想(v5 迭代的结论):LLM 判断"真缺陷"需要的是使用侧事实——
这个符号能不能走到失败路径;而不是告警文本本身。
"""
import json
from pathlib import Path

import clang.cindex


def _walk(node):
    """课2 的"逛树":从一棵树根开始一层层往下走。"""
    for child in node.get_children():
        yield child
        yield from _walk(child)


def _callee_name(node) -> str:
    """课2 的坑:CALL_EXPR 没有名字,被调者名字在子枝(DECL_REF_EXPR/MEMBER_REF_EXPR)上。"""
    for child in node.get_children():
        if child.kind in (clang.cindex.CursorKind.DECL_REF_EXPR,
                          clang.cindex.CursorKind.MEMBER_REF_EXPR):
            return child.spelling
    return ""


def _parse_tu(path: Path, repo: str):
    """课2 的方式"读书":带编译参数解析一个源文件为 AST 树。"""
    idx = clang.cindex.Index.create()
    args = ["-std=c++17", "-I" + str(Path(repo) / "include")]
    if path.suffix in (".h", ".hpp"):
        args += ["-x", "c++"]                    # 头文件按 C++ 读,否则按 C(课2 坑)
    return idx.parse(str(path), args=args)


def names_defined_in(path: Path, repo: str) -> set[str]:
    """告警文件里定义的名字 = "嫌疑名单"(函数/方法/类都算)。

    关键过滤(eval 的 v5 教训):include 进来的系统库声明(lldiv_t/free/...)
    不可能是"本文件定义的",必须按"定义位置在本文件"过滤,否则嫌疑名单被污染。
    """
    target = path.resolve()
    names = set()
    for node in _walk(_parse_tu(path, repo).cursor):
        if node.kind in (clang.cindex.CursorKind.FUNCTION_DECL,
                         clang.cindex.CursorKind.CXX_METHOD,     # 方法在 libclang 里叫 CXX_METHOD
                         clang.cindex.CursorKind.CONSTRUCTOR,    # CONSTRUCTOR_DECL 不存在
                         clang.cindex.CursorKind.CLASS_DECL,
                         clang.cindex.CursorKind.STRUCT_DECL):
            loc = node.location.file
            if loc is None:
                continue
            try:
                if Path(str(loc)).resolve() != target:   # 定义不在本文件 → 系统库/外部,排除
                    continue
            except OSError:
                continue
            names.add(node.spelling.split("<")[0])   # 模板去掉 <...>(课2 坑)
    return names


def build_call_index(repo: str) -> dict[str, list[str]]:
    """一次性索引:函数名 → 库内调用点的"文件:行"。

    只遍历 .cc(调用都发生在实现里);每个函数最多存 5 条调用点,防止内存膨胀。
    """
    db = json.loads((Path(repo) / "build" / "compile_commands.json").read_text())
    index: dict[str, list[str]] = {}
    for entry in db:
        src = Path(entry["file"])
        if src.suffix not in (".cc", ".cpp"):
            continue
        for node in _walk(_parse_tu(src, repo).cursor):
            if node.kind != clang.cindex.CursorKind.CALL_EXPR:
                continue
            f = node.location.file
            if f is None or not str(f).startswith(repo):
                continue
            callee = _callee_name(node)
            if not callee:
                continue
            lines = index.setdefault(callee, [])
            if len(lines) < 5:
                text = ""
                try:
                    src = Path(str(f)).read_text().splitlines()   # 课17 教训:只给行号不够
                    text = src[node.location.line - 1].strip()[:110]   # 要带"那行代码"给 LLM 看
                except Exception:
                    pass
                lines.append(f"{f}:{node.location.line}: {text}")
    return index
