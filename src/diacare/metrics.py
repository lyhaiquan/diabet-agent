def pass_at_k(results):
    """Tỷ lệ ca có ít nhất 1 lần chạy đạt (năng lực tối đa)."""
    return sum(any(v) for v in results.values()) / len(results) if results else 0.0


def pass_hat_k(results):
    """Tỷ lệ ca đạt ở cả k lần chạy (độ tin cậy lặp lại, Pass^k)."""
    return sum(all(v) for v in results.values()) / len(results) if results else 0.0


def summarize_usage(usages, chars_per_token):
    """Gộp số đo token/độ trễ; gợi ý CHARS_PER_TOKEN mới từ số đo thật."""
    usages = [u for u in usages if u and u.get("prompt_tokens")]
    if not usages:
        return {}
    n = len(usages)
    est = sum(u.get("est_prompt_tokens", 0) for u in usages)
    actual = sum(u["prompt_tokens"] for u in usages)
    return {
        "calls": n,
        "avg_prompt_tokens": actual / n,
        "avg_completion_tokens": sum(u.get("completion_tokens", 0) for u in usages) / n,
        "avg_seconds": sum(u.get("seconds", 0) for u in usages) / n,
        "max_prompt_tokens": max(u["prompt_tokens"] for u in usages),
        "near_limit_calls": sum(1 for u in usages
                                if u.get("num_ctx") and u["prompt_tokens"] >= 0.9 * u["num_ctx"]),
        "suggested_chars_per_token": round(chars_per_token * est / actual, 2) if est else None,
    }


def mcnemar_exact(b, c):
    """Kiểm định McNemar chính xác (nhị thức, hai phía) cho hai cấu hình chạy trên CÙNG bộ ca.
    b = số ca chỉ cấu hình A đạt, c = số ca chỉ cấu hình B đạt. Trả p-value; 1.0 nếu không có cặp lệch."""
    from math import comb
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def paired_outcomes(a, b):
    """a, b: {ca: [đạt?, ...]} của hai cấu hình. So theo ca (đạt = đạt mọi lượt, tức Pass^k) trên các ca chung.
    Trả bảng 2x2 và p-value McNemar. Các lượt của một ca không độc lập nên không ghép cặp theo lượt."""
    ids = [cid for cid in a if cid in b]
    both = sum(all(a[i]) and all(b[i]) for i in ids)
    only_a = sum(all(a[i]) and not all(b[i]) for i in ids)
    only_b = sum(all(b[i]) and not all(a[i]) for i in ids)
    return {"n_cases": len(ids), "both": both, "only_a": only_a, "only_b": only_b,
            "neither": len(ids) - both - only_a - only_b, "p_value": mcnemar_exact(only_a, only_b),
            "only_a_cases": [i for i in ids if all(a[i]) and not all(b[i])],
            "only_b_cases": [i for i in ids if all(b[i]) and not all(a[i])]}
