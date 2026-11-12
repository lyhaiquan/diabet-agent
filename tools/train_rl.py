"""Huấn luyện chính sách khởi động (warm start) cho RLAgent và lưu ra models/rl_policy.json.

Trạng thái lấy mẫu theo phân bố thật trong kb/rl/brfss_state_freq.json (tạo bằng tools/build_rl_states.py);
phần thưởng là điểm ưu tiên lâm sàng tiên nghiệm (rl.prior_reward), thang [-1, 1] như phản hồi 👍/👎.
Đánh giá trên trạng thái mới (hạt giống khác).

Tệp này là điểm xuất phát cố định. Khi chạy thật, mô hình học tiếp từ phản hồi và được lưu trong SQLite
(bảng rl_model), không ghi đè tệp này.

Chạy:  python tools/train_rl.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from diacare.rl import (DEFAULT_POLICY_PATH, PRIOR_STRENGTH, evaluate_policy, load_state_freq,  # noqa: E402
                        save_policy, train_policy)


def main():
    freq = load_state_freq()
    model = train_policy(n_samples=20000, prior_strength=PRIOR_STRENGTH, seed=42)
    metrics = evaluate_policy(model, n_eval=5000, seed=123)
    path = save_policy(model, DEFAULT_POLICY_PATH, meta={
        "eval_heldout": metrics, "prior_strength": PRIOR_STRENGTH, "train_samples": 20000,
        "state_source": freq["source"] if freq else "phân bố giả định (thiếu kb/rl/brfss_state_freq.json)"})
    print(f"Đã lưu {path}")
    print("Phần thưởng tiên nghiệm TB trên 5.000 trạng thái mới:", metrics)


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    main()
