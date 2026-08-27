"""P7: 建双语语料集合 cwe_bi(原 cwe 集合不动,保证历史实验可复现)。

文档 = 中文标题 + 中文描述 + 英文描述。用法:
    conda run -n cpp-review python eval/build_kb_bi.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)

import chromadb

from cpp_sentinel.data.cwe_knowledge import CWE_DOCS
from cpp_sentinel.data.cwe_knowledge_en import CWE_EN

client = chromadb.PersistentClient(path=str(Path(__file__).resolve().parents[1] / "data" / "chroma"))
col = client.get_or_create_collection("cwe_bi")

missing = [d["id"] for d in CWE_DOCS if d["id"] not in CWE_EN]
assert not missing, f"缺英文扩写: {missing}"

col.upsert(
    ids=[str(d["id"]) for d in CWE_DOCS],
    documents=[f'{d["title"]} {d["desc"]} | {CWE_EN[d["id"]]}' for d in CWE_DOCS],
    metadatas=[{"title": d["title"]} for d in CWE_DOCS],
)
print("cwe_bi 入库完成,条数:", col.count())
