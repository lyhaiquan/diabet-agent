from diacare.metrics import pass_at_k, pass_hat_k

RESULTS = {"a": [True, True, True], "b": [True, False, True], "c": [False, False, False]}


def test_pass_at_k_counts_any_success():
    assert pass_at_k(RESULTS) == 2 / 3


def test_pass_hat_k_requires_all_successes():
    assert pass_hat_k(RESULTS) == 1 / 3


def test_empty_results():
    assert pass_at_k({}) == 0.0 and pass_hat_k({}) == 0.0


from diacare.metrics import summarize_usage

USAGES = [
    {"prompt_tokens": 100, "completion_tokens": 20, "seconds": 2.0, "num_ctx": 4096, "est_prompt_tokens": 120},
    {"prompt_tokens": 300, "completion_tokens": 40, "seconds": 4.0, "num_ctx": 320, "est_prompt_tokens": 330},
]


def test_summarize_usage():
    s = summarize_usage(USAGES, 2.5)
    assert s["calls"] == 2
    assert s["avg_prompt_tokens"] == 200
    assert s["avg_completion_tokens"] == 30
    assert s["avg_seconds"] == 3.0
    assert s["max_prompt_tokens"] == 300
    assert s["near_limit_calls"] == 1
    assert s["suggested_chars_per_token"] == round(2.5 * 450 / 400, 2)


def test_summarize_usage_empty():
    assert summarize_usage([], 2.5) == {}
    assert summarize_usage([{}, {"seconds": 1.0}, None], 2.5) == {}


def test_mcnemar_exact():
    from diacare.metrics import mcnemar_exact
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(3, 3) == 1.0
    assert mcnemar_exact(0, 5) == 2 * 0.5 ** 5          # 0,0625
    assert abs(mcnemar_exact(1, 9) - 22 / 1024) < 1e-12  # 2 * (C(10,0)+C(10,1)) / 2^10
    assert mcnemar_exact(9, 1) == mcnemar_exact(1, 9)


def test_paired_outcomes_uses_all_runs_and_common_cases():
    from diacare.metrics import paired_outcomes
    a = {"x": [True, True], "y": [True, False], "z": [True, True], "only_a": [True]}
    b = {"x": [True, True], "y": [True, True], "z": [False, False], "only_b": [True]}
    r = paired_outcomes(a, b)
    assert (r["n_cases"], r["both"], r["only_a"], r["only_b"], r["neither"]) == (3, 1, 1, 1, 0)
    assert r["only_a_cases"] == ["z"] and r["only_b_cases"] == ["y"] and r["p_value"] == 1.0
