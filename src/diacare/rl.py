r"""Khối học tăng cường (Reinforcement Learning - V3): chọn trọng tâm tư vấn cá nhân hóa.

Bài toán:
- Luật an toàn y khoa (`diacare.rules`) là ràng buộc cứng, không bao giờ bị học tăng cường ghi đè.
- Tuy nhiên, một bệnh nhân có thể vừa thừa cân (BMI cao), vừa ít vận động, vừa có huyết áp/mỡ máu cao,
  hoặc đã có xét nghiệm bất thường. `RLAgent` đóng vai trò chính sách chọn hành động (policy) bằng
  Q-learning xấp xỉ tuyến tính trên trạng thái bệnh nhân $s$ (tổng hợp từ Predictor, LabAgent, MemoryAgent,
  hồ sơ BRFSS và câu hỏi hiện tại) để chọn chiến lược can thiệp trọng tâm $a \in \\mathcal{A}$ đưa vào ngữ cảnh
  cho Advisor.
- Hỗ trợ cả huấn luyện ngoại tuyến trên môi trường bệnh nhân mô phỏng (`train_policy`) lẫn cập nhật
  trực tuyến (`RLAgent.update`) từ phần thưởng phản hồi thực tế.
"""
import json
from pathlib import Path

import numpy as np

from diacare.labs import parse_lab_text, worst_level
from diacare.memory import has_diagnosis
from diacare.nutrition import is_nutrition_question, strip_accents
from diacare.rules import EMERGENCY_TERMS, SYMPTOM_TERMS, risk_band

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_POLICY_PATH = ROOT / "models" / "rl_policy.json"

# 6 hành động tư vấn trọng tâm: (mã hành động, nhãn ngắn hiển thị, hướng dẫn đưa vào ngữ cảnh Advisor)
ACTIONS = (
    ("urgent_eval", "Khám và xét nghiệm xác nhận sớm",
     "Nhấn mạnh người dùng cần đi khám bác sĩ sớm và làm xét nghiệm đường huyết xác nhận, không tự điều trị."),
    ("glycemic_followup", "Theo dõi đường huyết và tái khám định kỳ",
     "Nhấn mạnh việc theo dõi HbA1c/đường huyết định kỳ và tuân thủ đúng lịch tái khám của bác sĩ điều trị."),
    ("weight_diet", "Kiểm soát cân nặng và khẩu phần tinh bột",
     "Ưu tiên hướng dẫn kiểm soát cân nặng và chia khẩu phần ăn hợp lý (tăng chất xơ, giảm tinh bột tinh chế)."),
    ("physical_activity", "Tăng vận động thể lực đều đặn",
     "Ưu tiên hướng dẫn vận động thể lực đều đặn (ít nhất 150 phút/tuần như đi bộ nhanh) và giảm ngồi lâu."),
    ("cardio_control", "Kiểm soát huyết áp, mỡ máu và bỏ thuốc lá",
     "Ưu tiên nhắc kiểm soát huyết áp, mỡ máu và ngừng hút thuốc/hạn chế rượu bia để bảo vệ tim mạch."),
    ("preventive_habit", "Duy trì lối sống lành mạnh và tầm soát định kỳ",
     "Khuyến khích duy trì chế độ ăn nhiều rau xanh, vận động đều đặn và kiểm tra sức khỏe định kỳ hằng năm."),
)
ACTION_IDS = tuple(a[0] for a in ACTIONS)
ACTION_LABELS = {a[0]: a[1] for a in ACTIONS}
ACTION_GUIDANCE = {a[0]: a[2] for a in ACTIONS}

FEATURE_NAMES = (
    "bias",
    "risk_low",
    "risk_mid",
    "risk_high",
    "lab_alert",        # đường huyết ngưỡng ĐTĐ hoặc hạ đường huyết
    "lab_prediabetes",  # xét nghiệm mức tiền ĐTĐ
    "diagnosed",        # đã có chẩn đoán ĐTĐ trong trí nhớ
    "overweight",       # BMI >= 25 hoặc thiếu rau/trái cây
    "inactive",         # PhysActivity == 0
    "cardio_smoke",     # HighBP, HighChol, Smoker, hoặc HvyAlcoholConsump
    "topic_symptom",    # câu hỏi mô tả triệu chứng / cấp cứu / xét nghiệm
    "topic_lifestyle",  # câu hỏi hỏi về ăn uống hoặc vận động
)

_EXERCISE_WORDS = ("tap the duc", "van dong", "di bo", "chay bo", "the thao", "tap luyen", "ngoi nhieu")


def detect_topic(question, nutrition=None):
    """Phân loại chủ đề câu hỏi hiện tại để định hướng chính sách."""
    q = (question or "").lower()
    plain = strip_accents(q)
    if any(t in q for t in SYMPTOM_TERMS) or any(t in q for t in EMERGENCY_TERMS):
        return "symptom"
    if parse_lab_text(question or ""):
        return "lab"
    if is_nutrition_question(question or "", nutrition):
        return "nutrition"
    if any(w in plain for w in _EXERCISE_WORDS):
        return "exercise"
    return "general"


def extract_rl_state(state):
    """Rút trích từ điển trạng thái rời rạc từ `diacare.state.State`."""
    profile = state.profile or {}
    band = risk_band(state.risk) if state.risk is not None else "thấp"
    lab_lv = worst_level(state.labs or []) or "none"
    diag = has_diagnosis(state.memory or [])
    bmi = float(profile.get("BMI", 22.0))
    overweight = bmi >= 25.0 or int(profile.get("Fruits", 1)) == 0 or int(profile.get("Veggies", 1)) == 0
    inactive = int(profile.get("PhysActivity", 1)) == 0
    cardio_smoke = any(int(profile.get(k, 0)) == 1 for k in
                       ("HighBP", "HighChol", "Smoker", "HvyAlcoholConsump", "HeartDiseaseorAttack", "Stroke"))
    topic = detect_topic(state.question, state.nutrition)
    prev_action = None
    for m in reversed(state.history or []):
        if m.get("role") == "assistant" and m.get("rl_action"):
            prev_action = m["rl_action"]
            break
    return {
        "band": band,
        "lab": lab_lv,
        "diagnosed": bool(diag),
        "overweight": bool(overweight),
        "inactive": bool(inactive),
        "cardio_smoke": bool(cardio_smoke),
        "topic": topic,
        "prev_action": prev_action,
    }


def state_key(s):
    return (f"risk={s['band']}|lab={s['lab']}|diag={int(s['diagnosed'])}"
            f"|ow={int(s['overweight'])}|inact={int(s['inactive'])}"
            f"|cv={int(s['cardio_smoke'])}|topic={s['topic']}")


def state_vector(s):
    """Biểu diễn trạng thái thành vector đặc trưng 12 chiều $\\phi(s) \\in \\mathbb{R}^{12}$."""
    return np.array([
        1.0,
        1.0 if s["band"] == "thấp" else 0.0,
        1.0 if s["band"] == "trung bình" else 0.0,
        1.0 if s["band"] == "cao" else 0.0,
        1.0 if s["lab"] in ("diabetes", "low") else 0.0,
        1.0 if s["lab"] == "prediabetes" else 0.0,
        1.0 if s["diagnosed"] else 0.0,
        1.0 if s["overweight"] else 0.0,
        1.0 if s["inactive"] else 0.0,
        1.0 if s["cardio_smoke"] else 0.0,
        1.0 if s["topic"] in ("symptom", "lab") else 0.0,
        1.0 if s["topic"] in ("nutrition", "exercise") else 0.0,
    ], dtype=np.float64)


def clinical_reward(s, action, prev_action=None):
    """Hàm thưởng y khoa $R(s, a)$ phản ánh mức độ ưu tiên lâm sàng và kỳ vọng giảm nguy cơ BRFSS."""
    urgent = s["lab"] in ("diabetes", "low") or s["topic"] == "symptom" or (
        s["band"] == "cao" and not s["diagnosed"] and s["topic"] != "nutrition" and s["topic"] != "exercise")
    followup = s["diagnosed"] or s["lab"] == "prediabetes"

    if action == "urgent_eval":
        r = 3.2 if urgent else (1.2 if s["band"] == "cao" and not s["diagnosed"] else -1.2)
    elif action == "glycemic_followup":
        r = 2.8 if followup else (1.0 if s["topic"] == "lab" else -0.8)
    elif action == "weight_diet":
        r = (1.8 if s["overweight"] else -0.4) + (1.4 if s["topic"] == "nutrition" else 0.0)
        if urgent and s["topic"] != "nutrition":
            r -= 1.0
    elif action == "physical_activity":
        r = (1.9 if s["inactive"] else -0.4) + (1.4 if s["topic"] == "exercise" else 0.0)
        if urgent and s["topic"] != "exercise":
            r -= 1.0
    elif action == "cardio_control":
        r = 2.1 if s["cardio_smoke"] else -0.7
        if urgent:
            r -= 0.8
    elif action == "preventive_habit":
        healthy_low = (s["band"] == "thấp" and s["lab"] in ("none", "normal") and not s["diagnosed"]
                       and not s["overweight"] and not s["inactive"] and not s["cardio_smoke"])
        r = 2.6 if healthy_low else (0.5 if s["band"] == "thấp" and not urgent else -1.0)
    else:
        raise ValueError(f"hành động không hợp lệ: {action!r}")

    prev = prev_action if prev_action is not None else s.get("prev_action")
    if prev and prev == action and action not in ("urgent_eval",):
        r -= 0.8  # phạt lặp lại cùng một khuyến nghị lối sống giữa hai lượt liên tiếp
    return float(r)


def _step_simulated_patient(s, action, rng):
    """Mô phỏng chuyển trạng thái bệnh nhân $s \\to s'$ sau khi nhận khuyến nghị $a$."""
    ns = dict(s)
    ns["prev_action"] = action
    if action == "urgent_eval" and ns["band"] == "cao" and not ns["diagnosed"]:
        if rng.random() < 0.7:
            ns["diagnosed"] = True
    elif action == "weight_diet" and ns["overweight"] and rng.random() < 0.65:
        ns["overweight"] = False
    elif action == "physical_activity" and ns["inactive"] and rng.random() < 0.65:
        ns["inactive"] = False
    elif action == "cardio_control" and ns["cardio_smoke"] and rng.random() < 0.6:
        ns["cardio_smoke"] = False
    ns["topic"] = rng.choice(["general", "nutrition", "exercise", "lab", "symptom"],
                             p=[0.4, 0.25, 0.2, 0.1, 0.05])
    return ns


def _random_state(rng):
    return {
        "band": rng.choice(["thấp", "trung bình", "cao"], p=[0.4, 0.35, 0.25]),
        "lab": rng.choice(["none", "normal", "prediabetes", "diabetes", "low"], p=[0.45, 0.2, 0.15, 0.15, 0.05]),
        "diagnosed": bool(rng.random() < 0.25),
        "overweight": bool(rng.random() < 0.55),
        "inactive": bool(rng.random() < 0.45),
        "cardio_smoke": bool(rng.random() < 0.45),
        "topic": rng.choice(["general", "nutrition", "exercise", "lab", "symptom"],
                            p=[0.35, 0.25, 0.15, 0.15, 0.10]),
        "prev_action": None,
    }


def train_policy(episodes=2500, horizon=3, alpha=0.08, gamma=0.8, epsilon=0.25, seed=42):
    """Huấn luyện ma trận trọng số Q-learning tuyến tính $W \\in \\mathbb{R}^{|\\mathcal{A}| \\times d}$."""
    rng = np.random.default_rng(seed)
    n_actions = len(ACTION_IDS)
    n_features = len(FEATURE_NAMES)
    weights = np.zeros((n_actions, n_features), dtype=np.float64)

    for ep in range(episodes):
        s = _random_state(rng)
        eps = max(0.05, epsilon * (1.0 - ep / episodes))
        lr = max(0.01, alpha * (1.0 - 0.7 * ep / episodes))
        for _ in range(horizon):
            phi = state_vector(s)
            q_vals = weights @ phi
            if rng.random() < eps:
                a_idx = int(rng.integers(0, n_actions))
            else:
                a_idx = int(np.argmax(q_vals))
            act = ACTION_IDS[a_idx]
            r = clinical_reward(s, act)
            ns = _step_simulated_patient(s, act, rng)
            next_q = float(np.max(weights @ state_vector(ns)))
            td_error = r + gamma * next_q - float(q_vals[a_idx])
            weights[a_idx] += lr * td_error * phi
            s = ns
    return np.round(weights, 4)


def evaluate_policy(weights, n_eval=1000, seed=123):
    """So sánh phần thưởng trung bình mỗi lượt giữa chính sách Q-learning và chính sách ngẫu nhiên."""
    rng = np.random.default_rng(seed)
    q_rewards, rand_rewards = [], []
    for _ in range(n_eval):
        s = _random_state(rng)
        phi = state_vector(s)
        best_act = ACTION_IDS[int(np.argmax(weights @ phi))]
        rand_act = ACTION_IDS[int(rng.integers(0, len(ACTION_IDS)))]
        q_rewards.append(clinical_reward(s, best_act))
        rand_rewards.append(clinical_reward(s, rand_act))
    return {
        "q_mean_reward": round(float(np.mean(q_rewards)), 3),
        "random_mean_reward": round(float(np.mean(rand_rewards)), 3),
        "improvement": round(float(np.mean(q_rewards) - np.mean(rand_rewards)), 3),
    }


def save_policy(weights, path=None, meta=None):
    path = Path(path or DEFAULT_POLICY_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "algorithm": "linear_q_learning",
        "actions": list(ACTION_IDS),
        "features": list(FEATURE_NAMES),
        "weights": np.asarray(weights, dtype=float).tolist(),
        **(meta or {}),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_policy(path=None):
    path = Path(path or DEFAULT_POLICY_PATH)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        w = np.asarray(data["weights"], dtype=np.float64)
        if w.shape == (len(ACTION_IDS), len(FEATURE_NAMES)):
            return w
    return train_policy(episodes=1500, seed=42)


class RLAgent:
    """Agent học tăng cường (Q-learning): chọn hành động tư vấn trọng tâm tối ưu cho từng lượt."""

    def __init__(self, weights=None, alpha=0.05, gamma=0.8):
        self.weights = np.array(weights if weights is not None else load_policy(), dtype=np.float64, copy=True)
        self.alpha = alpha
        self.gamma = gamma

    def q_values(self, rl_state):
        phi = state_vector(rl_state)
        scores = self.weights @ phi
        if rl_state.get("prev_action") in ACTION_IDS and rl_state["prev_action"] != "urgent_eval":
            idx = ACTION_IDS.index(rl_state["prev_action"])
            scores = scores.copy()
            scores[idx] -= 0.8
        return scores

    def recommend(self, state):
        rl_state = extract_rl_state(state) if hasattr(state, "profile") else dict(state)
        scores = self.q_values(rl_state)
        order = np.argsort(-scores)
        best_idx = int(order[0])
        action = ACTION_IDS[best_idx]
        return {
            "action": action,
            "label": ACTION_LABELS[action],
            "guidance": ACTION_GUIDANCE[action],
            "q_value": round(float(scores[best_idx]), 2),
            "ranking": [(ACTION_IDS[int(i)], round(float(scores[int(i)]), 2)) for i in order[:3]],
            "state_key": state_key(rl_state),
        }

    def update(self, rl_state, action, reward, next_rl_state=None):
        """Cập nhật trực tuyến (online TD update) khi nhận phản hồi hoặc phần thưởng mới."""
        a_idx = ACTION_IDS.index(action)
        phi = state_vector(rl_state)
        q_sa = float(self.weights[a_idx] @ phi)
        next_max = float(np.max(self.weights @ state_vector(next_rl_state))) if next_rl_state else 0.0
        td_error = float(reward) + self.gamma * next_max - q_sa
        self.weights[a_idx] += self.alpha * td_error * phi
        return round(td_error, 4)


def format_rl(rl):
    """Khối ngữ cảnh định hướng từ RLAgent gửi cho Advisor."""
    if not rl or not rl.get("action"):
        return ""
    return (f"Định hướng tư vấn cá nhân hóa [rl_policy] (chính sách Q-learning, Q={rl['q_value']:+.2f}):\n"
            f"- Trọng tâm ưu tiên: {rl['label']}. {rl['guidance']}")
