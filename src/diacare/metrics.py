def pass_at_k(results):
    """Tỷ lệ ca có ít nhất 1 lần chạy đạt (năng lực tối đa)."""
    return sum(any(v) for v in results.values()) / len(results) if results else 0.0


def pass_hat_k(results):
    """Tỷ lệ ca đạt ở cả k lần chạy (độ tin cậy lặp lại, Pass^k)."""
    return sum(all(v) for v in results.values()) / len(results) if results else 0.0
