"""反馈记忆(P12): 人工复核结论落盘,后续判定做 few-shot 注入。

生产语义: bot 判完 → 人工复核(纠正或确认) → 追加进 memory.jsonl →
下次遇到同 check 告警,把历史结论注入 prompt。

与 P7 RAG 的本质区别: 注入的不是通用 CWE 知识(那个被证伪了),
而是"本仓库这个 check 的人工结论模式" —— 校准信息,不是知识。

检索纪律(防泄漏):
- 同 check 优先,候选超 k 时用 BM25 对 message 排序(英文↔英文,无 P6 跨语言坑)
- exclude_key 防自检索(评测时正在判的行绝不能检索到自己)
- 渲染不含文件路径(路径含 CWE 名 = 标签泄漏)
"""
import json
from pathlib import Path

from cpp_sentinel.retrieval import BM25

LABEL_CN = {"bug": "真问题", "noise": "误报", "unsure": "拿不准"}


class MemoryStore:
    """追加式记忆库: jsonl 持久化,只增不改(复核历史就是审计日志)。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.entries: list[dict] = []
        if self.path.exists():
            self.entries = [json.loads(l) for l in
                            self.path.read_text().splitlines() if l.strip()]

    def add(self, check: str, message: str, human_label: str,
            bot_decision: str = "", file: str = "", line: int = 0) -> None:
        """记一条人工结论。human_label: bug/noise/unsure(金标准词汇)。"""
        self.entries.append({"check": check, "message": message,
                             "human_label": human_label, "bot_decision": bot_decision,
                             "file": file, "line": line})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in self.entries) + "\n")

    def similar(self, check: str, message: str, k: int = 2,
                exclude_key: tuple | None = None) -> list[dict]:
        """同 check 优先;同 check 候选 > k 时按 BM25(message) 取 top-k;
        无同 check 时退回全库 BM25(词面无交集则空 = 诚实"无相关记忆")。"""
        pool = [e for e in self.entries
                if exclude_key is None or (e["file"], e["line"], e["check"]) != exclude_key]
        same = [e for e in pool if e["check"] == check]
        if len(same) <= k and same:
            return same
        ranked_pool = same if same else pool            # 同 check 太多→排序;没有→全库兜底
        scores = BM25([e["message"] for e in ranked_pool]).rank(message)
        if not scores:                                  # BM25 空 = 词面无交集
            return same[:k] if same else []
        return [ranked_pool[i] for i in scores[:k]]

    @staticmethod
    def render(entries: list[dict]) -> str:
        """few-shot 段落。不含文件路径(路径含 CWE 名 → 标签泄漏)。"""
        if not entries:
            return ""
        lines = ["=== 历史人工复核(相似告警的最终结论,供校准参考) ==="]
        for e in entries:
            prev = f"(bot 当时判 {e['bot_decision']})" if e.get("bot_decision") else ""
            lines.append(f"- check {e['check']}{prev} → 人工结论: "
                         f"{LABEL_CN.get(e['human_label'], e['human_label'])}\n"
                         f"  告警: {e['message'][:150]}")
        return "\n".join(lines)
