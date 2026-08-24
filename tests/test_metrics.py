from cpp_sentinel.metrics import compute_metrics


def test_known_matrix():
    gold = ["bug", "bug", "noise", "noise"]      # 答案:两个真、两个假
    pred = ["bug", "noise", "noise", "bug"]      # LLM:对上1个,漏1个,误报1个,正确忽略1个
    m = compute_metrics(gold, pred)
    assert m == {"tp": 1, "fp": 1, "fn": 1, "tn": 1,
                 "precision": 0.5, "recall": 0.5, "f1": 0.5, "n_graded": 4}


def test_perfect():
    gold = ["bug", "noise"]
    pred = ["bug", "noise"]
    m = compute_metrics(gold, pred)
    assert m["precision"] == 1.0 and m["recall"] == 1.0 and m["f1"] == 1.0


def test_unsure_in_pred_counts_as_miss_for_bug():
    gold = ["bug"]
    pred = ["unsure"]                            # LLM 犹豫 → 对 bug 算漏
    m = compute_metrics(gold, pred)
    assert m["fn"] == 1 and m["recall"] == 0.0


def test_gold_unsure_skipped():
    gold = ["unsure", "noise"]
    pred = ["bug", "noise"]                      # 金标准不确定那条,不参与
    m = compute_metrics(gold, pred)
    assert m["n_graded"] == 1 and m["fp"] == 0
