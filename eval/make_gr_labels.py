"""规则化预标注:把 dkvstore/mini 的判读经验编译成语义规则表,应用于 gr 30 条"""
import json
from pathlib import Path

SRC = Path("eval/dataset/alerts_gr.jsonl")
DST = Path("eval/dataset/labels.jsonl")

RULE = {
    "bugprone-derived-method-shadowing-base-method": ("noise", "方法名遮蔽,风格惯例"),
    "performance-enum-size": ("noise", "枚举宽度,无正确性影响"),
    "performance-type-promotion-in-math-fn": ("noise", "数学函数精度提升,可接受"),
    "bugprone-narrowing-conversions": ("noise", "double→float 窄化,工程可接受"),
    "bugprone-branch-clone": ("unsure", "switch 相同分支:可能故意并列,需人工核"),
    "bugprone-easily-swappable-parameters": ("noise", "易换参数,风格建议"),
    "bugprone-implicit-widening-of-multiplication-result": ("noise", "乘法隐式加宽,值域内安全"),
    "clang-diagnostic-inconsistent-missing-override": ("noise", "惯例"),
    "performance-avoid-endl": ("noise", "惯例"),
}

rows = [json.loads(l) for l in SRC.read_text().splitlines()][:30]
with DST.open("w") as f:
    for i, r in enumerate(rows):
        label, note = RULE.get(r["check"], ("unsure", "未知规则,请人工复核"))
        f.write(json.dumps({
            "idx": i, "file": r["file"], "line": r["line"], "check": r["check"],
            "message": r["message"], "label": label, "note": note,
        }, ensure_ascii=False) + "\n")

print(f"规则预填 30 条 → {DST}(unsure 数:{sum(1 for r in rows if RULE.get(r['check'],('unsure',''))[0]=='unsure')})")
