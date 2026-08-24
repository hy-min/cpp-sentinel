"""把告警池转成标注模板:取前 30 条,label 待你填"""
import json
from pathlib import Path

SRC = Path("eval/dataset/alerts.jsonl")
DST = Path("eval/dataset/labels.jsonl")

alerts = [json.loads(l) for l in SRC.read_text().splitlines()][:30]

with DST.open("w") as f:
    for i, a in enumerate(alerts):
        f.write(json.dumps({
            "idx": i,                              # 编号(标注时填这个号就行)
            "file": a["file"],                     # 每条:出处(告诉你去哪查源码)
            "line": a["line"],
            "check": a["check"],
            "message": a["message"],
            "label": "",                           # ← 你填: bug / noise / unsure
            "note": "",                            # ← 你填: 一句话为什么(防自己健忘,素材!)
        }, ensure_ascii=False) + "\n")

print(f"{len(alerts)} 条标注模板 → {DST}")
