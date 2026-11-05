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
