"""自包含:不用本地 data/chroma,自己建临时库——任何机器(含 CI)都能过"""
import chromadb


def test_query_hits_cwe476(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path))     # 临时库,pytest 自动清理
    col = client.get_or_create_collection("cwe")
    col.upsert(
        ids=["1"],
        documents=["CWE-476 空指针解引用：解引用空指针访问内存，导致崩溃"],
    )
    res = col.query(query_texts=["空指针导致程序崩溃"], n_results=1)
    assert "CWE-476" in res["documents"][0][0]                # 命中的文档包含编号
