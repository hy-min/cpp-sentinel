import clang.cindex                            # 开天门工具的钥匙包
from collections import Counter                # 计数器:数种类多少的小工具

idx = clang.cindex.Index.create()              # 造一个"读者",专门读 C++ 文件
tu = idx.parse(
    '/home/hy/dkvstore/include/dkvstore/common/status.h',   # 请读者读这个文件
    args=[
        '-std=c++17',                          # 规则①:按 C++17 语法书读
        '-I/home/hy/dkvstore/include',         # 规则②:材料库/头文件都在这个目录
        '-x', 'c++'                            # 规则③:这是 C++ 课文,别按 C 读
    ]
)
print('parse errors:', len(tu.diagnostics))    # 树长得顺不顺?报错数(0 = 顺利)
for d in tu.diagnostics:
    print('  diag:', d)
kinds = Counter(n.kind.name for n in tu.cursor.walk_preorder())  # 逛树(从根开始一层层),数每类节点
for k, v in kinds.most_common(10):
    print(f'  {k}: {v}')                       # 清单:"树里都有哪种家伙、各多少个"

print('--- dkvstore 代码里,谁调用了什么 ---')
from collections import Counter as C
calls = C()
for node in tu.cursor.walk_preorder():                    # 逛整棵树
    if node.kind == clang.cindex.CursorKind.CALL_EXPR:    # 只留"调用"这种枝
        f = node.location.file
        if f is not None and str(f).startswith('/home/hy/dkvstore'):   # 只留自家园的
            calls[node.spelling] += 1
for name, cnt in calls.most_common(10):
    print(f'  {name}: {cnt}')                             # 谁被调得最多