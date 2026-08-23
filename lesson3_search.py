import os
for v in ["ALL_PROXY", "all_proxy"]:                            # ★ 只删"未知协议"那两条(socks)
    os.environ.pop(v, None)                                    #   http 代理保留,httpx 会用它

import chromadb                                                 # ① 把"开箱工具"拿进页
client = chromadb.PersistentClient(path="data/chroma")          # ② 重新打开存储箱
col = client.get_or_create_collection("cwe")                    # ③ 找回上次那个"格子集"
result = col.query(query_texts=["空指针导致程序崩溃"],            # ④ 问它:哪条知识跟"空指针"相关
                   n_results=1)                                 #   只取最相关的 1 条
print(result)                                                   # ⑤ 先看原始返回长啥样
print('命中的标题:', result['metadatas'][0][0]['title'])         # ⑥ 取出那一条的 title
