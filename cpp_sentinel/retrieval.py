"""检索器三式消融(P6): 向量 / BM25 / 混合(RRF) —— 同语料同查询,只换检索方法。

语料来自 chroma(cwe 集合, 50 条中文 CWE 条目)。判定查询是英文告警文本
→ BM25 面临跨语言词面鸿沟, 这本身是被测对象之一。
"""
import math
import re
from pathlib import Path

CHROMA = str(Path(__file__).resolve().parents[1] / "data" / "chroma")


def _tokenize(text: str) -> list[str]:
    """ASCII 词干 + CJK 单字/二元组(无 jieba 依赖的 CJK BM25 常规做法)。"""
    toks = re.findall(r"[a-zA-Z0-9]+", text.lower())
    cjk = re.findall(r"[一-鿿]", text)
    toks += cjk
    toks += [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    return toks


def load_corpus(collection: str = "cwe"):
    """从 chroma 读出全量语料(向量检索仍走 chroma,这里只为对齐 id→索引)。"""
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA)
    col = client.get_collection(collection)
    got = col.get(include=["documents", "metadatas"])
    rows = [{"id": i, "doc": d, "title": (m or {}).get("title", "")}
            for i, d, m in zip(got["ids"], got["documents"], got["metadatas"])]
    return client, col, rows


class BM25:
    """手写 BM25(k1=1.5, b=0.75),零依赖。"""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        from collections import Counter
        self.k1, self.b = k1, b
        self.toks = [_tokenize(d) for d in docs]
        self.tf = [Counter(t) for t in self.toks]
        self.dl = [len(t) for t in self.toks]
        self.N = len(docs)
        self.avgdl = sum(self.dl) / max(self.N, 1)
        df = Counter()
        for t in self.toks:
            for w in set(t):
                df[w] += 1
        self.df = df

    def _idf(self, t: str) -> float:
        n = self.df.get(t, 0)
        return math.log(1 + (self.N - n + 0.5) / (n + 0.5))

    def rank(self, query: str) -> list[int]:
        """返回按分数降序的文档索引;全零(词面无交集)时返回空表=检不到。"""
        q = _tokenize(query)
        scored = []
        for i in range(self.N):
            s = 0.0
            for t in q:
                f = self.tf[i].get(t, 0)
                if f:
                    s += self._idf(t) * f * (self.k1 + 1) / (
                        f + self.k1 * (1 - self.b + self.b * self.dl[i] / self.avgdl))
            scored.append((s, i))
        scored.sort(key=lambda x: -x[0])
        if not scored or scored[0][0] <= 0:
            return []                                   # 词面无交集,如实返回空
        return [i for _, i in scored]


class Retriever:
    """三种检索法统一接口: query → (top1_title, top1_doc, debug)"""

    def __init__(self, mode: str, collection: str = "cwe"):
        assert mode in ("vector", "bm25", "hybrid")
        self.mode = mode
        self.client, self.col, self.rows = load_corpus(collection)
        self.bm25 = BM25([r["doc"] for r in self.rows])
        self.id2idx = {r["id"]: i for i, r in enumerate(self.rows)}

    def _vector_rank(self, query: str) -> list[int]:
        hit = self.col.query(query_texts=[query], n_results=len(self.rows))
        return [self.id2idx[i] for i in hit["ids"][0]]

    def query(self, text: str):
        if self.mode == "vector":
            order = self._vector_rank(text)
        elif self.mode == "bm25":
            order = self.bm25.rank(text)
        else:                                           # hybrid: RRF(k=60) 融合
            v = self._vector_rank(text)
            b = self.bm25.rank(text)
            rrf = {}
            for rank_list in (v, b):
                for rank, idx in enumerate(rank_list):
                    rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (60 + rank + 1)
            order = sorted(rrf, key=lambda i: -rrf[i])
        if not order:
            return None, None, "no-hit"
        top = self.rows[order[0]]
        return top["title"], top["doc"], f"{self.mode}:top1={top['id']}"
