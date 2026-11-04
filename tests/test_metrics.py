from diacare.metrics import pass_at_k, pass_hat_k

RESULTS = {"a": [True, True, True], "b": [True, False, True], "c": [False, False, False]}


def test_pass_at_k_counts_any_success():
    assert pass_at_k(RESULTS) == 2 / 3


def test_pass_hat_k_requires_all_successes():
    assert pass_hat_k(RESULTS) == 1 / 3


def test_empty_results():
    assert pass_at_k({}) == 0.0 and pass_hat_k({}) == 0.0
