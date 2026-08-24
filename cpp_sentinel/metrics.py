"""metrics:精度/召回/F1 —— eval 的核心数学"""
from typing import List


def compute_metrics(gold: List[str], pred: List[str]) -> dict:
    """gold/pred: 每条都是 'bug' | 'noise' | 'unsure'
    规则:
    - "bug" 是正类(我们要抓的东西)
    - pred 判 "unsure" 算"没判" → 如果 gold 是 bug,记漏(fn);gold 是 noise,不算错
    - gold 本身是 "unsure" 的样本,金标准不明,跳过不计入
    """
    tp = fp = fn = tn = 0
    for g, p in zip(gold, pred):
        if g == "unsure":
            continue                             # 金标准不清楚,跳过
        if p == "bug" and g == "bug":
            tp += 1                              # 猜对了:真问题被判真问题
        elif p == "bug" and g == "noise":
            fp += 1                              # 误报:噪音被当成真问题
        elif p != "bug" and g == "bug":
            fn += 1                              # 漏报:真问题被判成噪音/未判
        elif p != "bug" and g == "noise":
            tn += 1                              # 正确忽略:值得表扬,但也算分

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "n_graded": tp + fp + fn + tn,           # 参与评判的有效样本数(四态都算)
    }
