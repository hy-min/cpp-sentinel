import chromadb                              # ① 还是这个开箱工具

def test_query_hits_cwe476():
    client = chromadb.PersistentClient(path="data/chroma")   # ② 打开同一个箱子(数据在)
    col = client.get_or_create_collection("cwe")             # ③ 找到"cwe"集合
    result = col.query(query_texts=["空指针导致程序崩溃"], n_results=1)   # ④ 同一个检索动作
    title = result["metadatas"][0][0]["title"]               # ⑤ 取出命中的 title
    assert "CWE-476" in title                                # ⑥ 断言:命中 CWE-476
