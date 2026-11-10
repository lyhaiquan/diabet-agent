"""Huấn luyện chính sách Q-learning cho RLAgent (V3) và lưu ra models/rl_policy.json.

Chạy:  python tools/train_rl.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from diacare.rl import DEFAULT_POLICY_PATH, evaluate_policy, save_policy, train_policy  # noqa: E402


def main():
    weights = train_policy(episodes=3000, horizon=3, alpha=0.08, gamma=0.8, epsilon=0.25, seed=42)
    metrics = evaluate_policy(weights, n_eval=1000, seed=123)
    path = save_policy(weights, DEFAULT_POLICY_PATH, meta={"eval": metrics})
    print(f"Đã lưu chính sách RL tại {path}")
    print(f"Phần thưởng TB (Q-learning): {metrics['q_mean_reward']:+.3f} vs Ngẫu nhiên: {metrics['random_mean_reward']:+.3f} "
          f"(+{metrics['improvement']:.3f})")


if __name__ == "__main__":
    main()
