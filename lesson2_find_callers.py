import clang.cindex

idx = clang.cindex.Index.create()                     # 读者
tu = idx.parse(
    'tests/fixtures/callers_sample.cpp',              # 读自己造的小文件(干净!)
    args=['-std=c++17', '-x', 'c++']                  # 就两条规则
)

target = 'helper'                                     # 我们要找:谁调用了 helper

def walk(node, func):                                 # 逛树,手里要知道"当前在哪个函数里"
    for child in node.get_children():
        if child.kind == clang.cindex.CursorKind.DECL_REF_EXPR and child.spelling == target:
            if func is not None:
                print(f'  "{target}" 被 "{func.spelling}" 调用 @ line {func.location.line}')
        f2 = func
        if child.kind in (clang.cindex.CursorKind.FUNCTION_DECL,
                          clang.cindex.CursorKind.CXX_METHOD):
            f2 = child                                # 走进函数体,当前函数换成它
        walk(child, f2)

print(f'反查 "{target}" 的调用者:\n')
walk(tu.cursor, None)
