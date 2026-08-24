"""三臂消融: A=裸静态 / B=+LLM / C=+LLM+RAG → 同一"磅秤"出分"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))    # 认祖(同 dump_alerts.py)

for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)                                     # R1 铁律

from openai import OpenAI

from cpp_sentinel.metrics import compute_metrics
from cpp_sentinel.review import build_prompt, parse_response

ROOT = Path(__file__).resolve().parents[1]
LABELS = [json.loads(l) for l in (ROOT / "eval" / "dataset" / "labels.jsonl").read_text().splitlines()]

REPO = sys.argv[1] if len(sys.argv) > 1 else "/home/hy/dkvstore"
CC_FILES = [e["file"] for e in json.loads((Path(REPO) / "build" / "compile_commands.json").read_text())
            if e["file"].endswith((".cc", ".cpp"))]

def extract_names(header: str) -> list[str]:
    """v5:用课 2 的 AST 手法,提取 header 里定义的 类/函数/方法名"""
    import clang.cindex
    idx = clang.cindex.Index.create()
    tu = idx.parse(header, args=["-std=c++17", "-I" + str(Path(REPO) / "include"), "-x", "c++"])
    names = set()
    kinds = (clang.cindex.CursorKind.CLASS_DECL, clang.cindex.CursorKind.CXX_METHOD,
             clang.cindex.CursorKind.FUNCTION_DECL, clang.cindex.CursorKind.CONSTRUCTOR)
    for n in tu.cursor.walk_preorder():
        if n.kind in kinds:
            loc = n.location.file
            # 只要"定义在这个 header 里"的名字——系统库的别收(课2:只留自家园)
            if n.spelling and loc is not None and str(loc).endswith(Path(header).name) \
               and "operator" not in n.spelling:
                names.add(n.spelling.split("<")[0])     # Result<T> → Result
    return list(names)

# ---------- P2: AST 调用索引(真正的"谁调用了谁",课 2 工厂化) ----------
_CALL_INDEX = None


def build_call_index():
    """全仓库扫描一遍,建立 {符号名: [(文件,行,所在函数)]} 索引(每进程只建一次)"""
    global _CALL_INDEX
    if _CALL_INDEX is not None:
        return _CALL_INDEX
    import clang.cindex
    reader = clang.cindex.Index.create()
    index = {}
    for f in CC_FILES:
        try:
            tu = reader.parse(f, args=["-std=c++17", "-I" + str(Path(REPO) / "include")])
        except Exception:
            continue

        def walk(node, func):
            for child in node.get_children():
                f2 = func
                if child.kind in (clang.cindex.CursorKind.FUNCTION_DECL,
                                  clang.cindex.CursorKind.CXX_METHOD):
                    f2 = child.spelling                       # 走入函数体,记住当前函数
                if child.kind in (clang.cindex.CursorKind.DECL_REF_EXPR,
                                  clang.cindex.CursorKind.MEMBER_REF_EXPR) and child.spelling:
                    loc = child.location
                    if loc.file is not None and str(loc.file).startswith(REPO):
                        index.setdefault(child.spelling, []).append(
                            (Path(f).name, loc.line, f2 or ""))
                walk(child, f2)

        walk(tu.cursor, None)
    _CALL_INDEX = index
    return index


def ast_callers(header: str) -> str:
    """P2 使用侧:查 AST 索引,输出该 header 定义的每个符号被谁引用(带调用者)"""
    if not header.endswith((".h", ".hpp")):
        return ""
    names = extract_names(header)
    index = build_call_index()
    rows, seen = [], set()
    for name in names:
        for f, line, fn in sorted(index.get(name, []), key=lambda x: (x[1])):
            key = (f, line, fn, name)
            if key in seen:
                continue
            seen.add(key)
            rows.append(f"{f}:{line} ({fn}) 引用 {name}")
            if len(rows) >= 12:
                break
        if len(rows) >= 12:
            break
    return "\n".join(rows)


USE_ACTIONS = ("Result<", "Result(", "Status(", ".Value(", ".TakeValue(", ".IsOk(", "ErrorCode::")

def usage_side(header: str) -> str:
    """v5:跨文件抓'真实使用动作行' → '使用侧证据'(不匹配名字,匹配动作)"""
    if not header.endswith((".h", ".hpp")):
        return ""
    out = []
    for f in CC_FILES:
        try:
            lines = Path(f).read_text(errors="ignore").splitlines()
        except OSError:
            continue
        hits = 0
        for i, ln in enumerate(lines):
            if any(act in ln for act in USE_ACTIONS):
                out.append(f"{Path(f).name}:{i+1}: {ln.strip()[:100]}")
                hits += 1
                if hits >= 4:
                    break
        if len(out) >= 12:
            break
    return "\n".join(out)

def arm_static():
    """A 臂:所有告警都判'bug'(静态工具全报,不做鉴别)"""
    return ["bug"] * len(LABELS)                                # 全枪毙=全报

def source_snippet(file: str, line: int, span: int = 25) -> str:
    """v4:短文件给全文(len<120),长文件给 ±span 行窗口 —— 让模型自己找到使用路径"""
    p = Path(file)
    if not p.exists():
        return "(源文件不可读)"
    lines = p.read_text(errors="ignore").splitlines()
    if len(lines) <= 120:
        return "\n".join(f"{i+1}: {lines[i]}" for i in range(len(lines)))   # 全文
    lo, hi = max(0, line - span), min(len(lines), line + span)
    return "\n".join(f"{i+1}: {lines[i]}" for i in range(lo, hi))


def llm_judge(use_rag: bool):
    """B/C 臂:LLM 逐条判;use_rag 控制是否附带知识库条款"""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("请先设置: export DEEPSEEK_API_KEY=<你的key>")
    client = OpenAI(base_url="https://api.deepseek.com/v1",
                    api_key=os.environ["DEEPSEEK_API_KEY"])
    preds = []
    for row in LABELS:
        alert = (f"{row['file']}:{row['line']}: {row['check']}\n{row['message']}")
        ctx = []
        if use_rag:                                             # C 臂多一步:查知识库
            import chromadb
            chroma = chromadb.PersistentClient(path=str(Path("/home/hy/dkvstore") / "data" / "chroma"))
            col = chroma.get_or_create_collection("cwe")
            hit = col.query(query_texts=[row["message"]], n_results=1)
            if hit["ids"][0]:
                ctx.append("相关规范: " + hit["metadatas"][0][0]["title"])
        ctx.append("=== 源码证据 ===\n" + source_snippet(row["file"], row["line"]))
        usage = ast_callers(row["file"])                      # P2:AST 调用链证据(替代行匹配版)
        if usage:
            ctx.append("=== 调用链证据(AST 级别) ===\n" + usage)
        ctx = "\n".join(ctx)
        prompt = f"{RUBRIC}\n\n=== 告警 ===\n{alert}\n=== 背景 ===\n{ctx}"
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        try:
            preds.append(parse_response(resp.choices[0].message.content).decision)
        except ValueError:
            preds.append("unsure")                              # 乱答=没判(计漏)
        print(f"  {len(preds)}/{len(LABELS)}", end="\r")
    print()
    return preds

RUBRIC = """你是 C++ 静态审查助手。针对告警与上下文,判定:
- real: 证据充分(如:被广泛调用、路径可达、符合 CWE)→ 真问题
- suspicious: 证据不足,值得人工再看
- ignore: 误报/风格问题
=== 强谓词规则(重要) ===
- 若 check 名含 optional 且 message 描述"未检查访问"(unchecked access),或属 clang-analyzer
  的内存安全类,或 message 含 accessing/memory/overflow 等词:除非有明确反证,应判 real 或 suspicious,
  不要判 ignore —— 宁可保守,不可漏检。
只输出 JSON: {"decision": "...", "reason": "一句话理由", "confidence": 0.x}"""

def main():
    gold = [r["label"] for r in LABELS]
    print("=== A 臂: 裸静态(全报) ===")
    print(compute_metrics(gold, arm_static()))
    print("\n=== B 臂: +LLM ===")
    preds_b = llm_judge(use_rag=False)
    (ROOT / "eval" / "results").mkdir(exist_ok=True)
    (ROOT / "eval" / "results" / "arm_llm_v7.jsonl").write_text(json.dumps(preds_b))   # v7(AST 调用链)
    print(compute_metrics(gold, preds_b))
    print("\n=== C 臂: +LLM+RAG (v7) ===")
    preds_c = llm_judge(use_rag=True)
    (ROOT / "eval" / "results" / "arm_rag_v7.jsonl").write_text(json.dumps(preds_c))
    print(compute_metrics(gold, preds_c))

if __name__ == "__main__":
    main()
