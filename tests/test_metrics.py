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
