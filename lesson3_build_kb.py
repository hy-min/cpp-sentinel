import chromadb
from cpp_sentinel.data.cwe_knowledge import CWE_DOCS

client = chromadb.PersistentClient(path="data/chroma")          # 收件箱:向量库存在 data/chroma 目录
col = client.get_or_create_collection("cwe")                    # 建一个名为 cwe 的"格子"集

# 把 5 条知识放进去:每条 = id + 文本正文 + 备注
col.upsert(
    ids=[str(d["id"]) for d in CWE_DOCS],
    documents=[f'{d["title"]} {d["desc"]}' for d in CWE_DOCS],
    metadatas=[{"title": d["title"]} for d in CWE_DOCS],
)

print("入库完成,库里条数:", col.count())                        # 应打印 5
