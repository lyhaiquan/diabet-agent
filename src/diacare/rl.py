r"""Agent học tăng cường: chọn trọng tâm tư vấn và học từ phản hồi của người dùng.

Bài toán (contextual bandit, Sutton & Barto ch. 2, mục 2.9):
- Mỗi lượt hỏi, agent thấy một trạng thái $s$ (mức nguy cơ, xét nghiệm, đã chẩn đoán, thừa cân, ít vận động,
  tim mạch, chủ đề câu hỏi) và chọn một trong 6 trọng tâm tư vấn $a$. Câu hướng dẫn của $a$ được đưa vào
  ngữ cảnh của Advisor.
- Người dùng chấm trọng tâm đó bằng 👍 (+1) hoặc 👎 (-1). Đó là phần thưởng $r$ của đúng cặp $(s, a)$.
- Không quan sát được trạng thái sức khỏe kế tiếp của người dùng, nên không có bước chuyển $s \to s'$ để
  bootstrap: mỗi lượt là một bài toán một bước, $\gamma = 0$. Đây là học tăng cường với phản hồi đánh giá
  (evaluative feedback), không phải học có giám sát: agent chỉ biết phần thưởng của hành động nó đã chọn.

Mô hình: hồi quy ridge tuyến tính cho từng hành động, $\hat r_a(s) = w_a^\top \phi(s)$ với
$w_a = A_a^{-1} b_a$, $A_a = \lambda I + \sum \phi\phi^\top$, $b_a = \sum r \phi$ (như LinUCB của Li et al. 2010,
chọn hành động bằng epsilon-greedy thay cho cận tin cậy trên để ghi được xác suất chọn).

Ba lớp an toàn:
1. Mặt nạ an toàn: xét nghiệm ở ngưỡng tiểu đường / hạ đường huyết, hoặc câu hỏi có triệu chứng, cấp cứu,
   thì luôn chọn "khám sớm", xác suất 1, không thăm dò.
2. Thăm dò epsilon-greedy chỉ chọn giữa 6 trọng tâm đều là lời khuyên an toàn; mỗi quyết định ghi lại
   xác suất chọn (propensity) để đánh giá ngoài chính sách (IPS, SNIPS).
3. Agent Rules vẫn chạy sau cùng và quyết định câu trả lời cuối; RL không ghi đè được.

Khởi động (warm start): trước khi có phản hồi thật, chính sách học từ phần thưởng tiên nghiệm
`prior_reward` (mức ưu tiên lâm sàng do nhóm đặt, thang [-1, 1]) trên trạng thái lấy mẫu từ phân bố thật
của BRFSS 2015 (kb/rl/brfss_state_freq.json). Độ nặng của tiên nghiệm bằng `prior_strength` lượt quan sát
mỗi hành động, nên phản hồi thật dần lấn át tiên nghiệm.
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
DEFAULT_STATE_FREQ = ROOT / "kb" / "rl" / "brfss_state_freq.json"

DEFAULT_EPSILON = 0.1        # tỉ lệ thăm dò khi chạy thật; benchmark đặt 0
REPEAT_PENALTY = 0.25        # trừ điểm trọng tâm vừa dùng ở lượt trước (trừ "khám sớm")
RIDGE_LAMBDA = 1.0
PRIOR_STRENGTH = 30          # tiên nghiệm nặng bằng chừng này lượt phản hồi cho mỗi hành động
FEEDBACK_REWARD = {"up": 1.0, "down": -1.0}

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
    "cardio_smoke",     # HighBP, HighChol, Smoker, rượu bia nhiều, bệnh tim hoặc đột quỵ
    "topic_symptom",    # câu hỏi mô tả triệu chứng / cấp cứu / xét nghiệm
    "topic_lifestyle",  # câu hỏi hỏi về ăn uống hoặc vận động
    "high_undiagnosed",  # nguy cơ cao mà chưa chẩn đoán: tương tác mà mô hình tuyến tính không tự học được
)

_EXERCISE_WORDS = ("tap the duc", "van dong", "di bo", "chay bo", "the thao", "tap luyen", "ngoi nhieu")
_TOPICS = ("general", "nutrition", "exercise", "lab", "symptom")


# ---------- trạng thái ----------

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


def profile_flags(profile):
    """Ba đặc trưng lấy từ hồ sơ BRFSS; dùng chung cho lúc chạy và lúc tính phân bố từ dữ liệu."""
    profile = profile or {}
    bmi = float(profile.get("BMI", 22.0))
    return {
        "overweight": bmi >= 25.0 or int(profile.get("Fruits", 1)) == 0 or int(profile.get("Veggies", 1)) == 0,
        "inactive": int(profile.get("PhysActivity", 1)) == 0,
        "cardio_smoke": any(int(profile.get(k, 0)) == 1 for k in
                            ("HighBP", "HighChol", "Smoker", "HvyAlcoholConsump", "HeartDiseaseorAttack", "Stroke")),
    }


def extract_rl_state(state):
    """Rút trích từ điển trạng thái rời rạc từ `diacare.state.State`."""
    band = risk_band(state.risk) if state.risk is not None else "thấp"
    prev_action = None
    for m in reversed(state.history or []):
        if m.get("role") == "assistant" and m.get("rl_action"):
            prev_action = m["rl_action"]
            break
    return {
        "band": band,
        "lab": worst_level(state.labs or []) or "none",
        "diagnosed": bool(has_diagnosis(state.memory or [])),
        **{k: bool(v) for k, v in profile_flags(state.profile).items()},
        "topic": detect_topic(state.question, state.nutrition),
        "prev_action": prev_action,
    }


def state_key(s):
    return (f"risk={s['band']}|lab={s['lab']}|diag={int(s['diagnosed'])}"
            f"|ow={int(s['overweight'])}|inact={int(s['inactive'])}"
            f"|cv={int(s['cardio_smoke'])}|topic={s['topic']}")


def state_vector(s):
    """Biểu diễn trạng thái thành vector đặc trưng 13 chiều $\\phi(s) \\in \\mathbb{R}^{13}$."""
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
        1.0 if s["band"] == "cao" and not s["diagnosed"] else 0.0,
    ], dtype=np.float64)


def is_urgent(s):
    """Mặt nạ an toàn: các trạng thái này luôn phải khuyên đi khám, không để chính sách thăm dò."""
    return s["lab"] in ("diabetes", "low") or s["topic"] == "symptom"


# ---------- phần thưởng tiên nghiệm ----------

def clinical_reward(s, action, prev_action=None):
    """Điểm ưu tiên lâm sàng do nhóm đặt (thang gốc, khoảng -2,2 đến 3,2). Chỉ dùng để khởi động."""
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


def prior_reward(s, action):
    """Phần thưởng tiên nghiệm cùng thang với phản hồi thật: [-1, 1] (👎 = -1, 👍 = +1)."""
    return float(np.clip(clinical_reward(s, action, prev_action=None) / 3.2, -1.0, 1.0))


# ---------- lấy mẫu trạng thái theo phân bố thật ----------

def load_state_freq(path=DEFAULT_STATE_FREQ):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _choice(rng, items, weights):
    w = np.asarray(weights, dtype=float)
    return items[int(rng.choice(len(items), p=w / w.sum()))]


def sample_state(rng, freq=None):
    """Hồ sơ lấy theo tần suất BRFSS thật, chủ đề theo bộ ca benchmark; xét nghiệm, chẩn đoán theo tỉ lệ giả định."""
    if freq is None:
        prof = {"band": _choice(rng, ["thấp", "trung bình", "cao"], [0.4, 0.35, 0.25]),
                "overweight": bool(rng.random() < 0.55), "inactive": bool(rng.random() < 0.45),
                "cardio_smoke": bool(rng.random() < 0.45)}
        topics = dict(zip(_TOPICS, (0.35, 0.25, 0.15, 0.15, 0.10)))
        lab_prior = {"none": 0.45, "normal": 0.2, "prediabetes": 0.15, "diabetes": 0.15, "low": 0.05}
        diag_prior = 0.25
    else:
        profiles = freq["profiles"]
        prof = dict(_choice(rng, profiles, [p["n"] for p in profiles]))
        prof.pop("n", None)
        topics, lab_prior, diag_prior = freq["topics"], freq["lab_prior"], freq["diagnosed_prior"]
    return {
        **prof,
        "lab": _choice(rng, list(lab_prior), list(lab_prior.values())),
        "diagnosed": bool(rng.random() < diag_prior),
        "topic": _choice(rng, list(topics), list(topics.values())),
        "prev_action": None,
    }


# ---------- mô hình tuyến tính cho từng hành động ----------

class LinearBandit:
    """$\\hat r_a(s) = w_a^\\top \\phi(s)$, $w_a = A_a^{-1} b_a$. Cập nhật một phản hồi: $A_a += \\phi\\phi^\\top$, $b_a += r\\phi$."""

    def __init__(self, A=None, b=None, n_updates=0, lam=RIDGE_LAMBDA):
        k, d = len(ACTION_IDS), len(FEATURE_NAMES)
        self.A = np.array(A, dtype=np.float64) if A is not None else np.stack([lam * np.eye(d)] * k)
        self.b = np.array(b, dtype=np.float64) if b is not None else np.zeros((k, d))
        self.n_updates = int(n_updates)

    def weights(self):
        return np.stack([np.linalg.solve(self.A[i], self.b[i]) for i in range(len(ACTION_IDS))])

    def predict(self, s):
        return self.weights() @ state_vector(s)

    def update(self, s, action, reward):
        i, phi = ACTION_IDS.index(action), state_vector(s)
        self.A[i] += np.outer(phi, phi)
        self.b[i] += float(reward) * phi
        self.n_updates += 1

    def copy(self):
        return LinearBandit(self.A.copy(), self.b.copy(), self.n_updates)

    def to_dict(self):
        return {"A": self.A.round(6).tolist(), "b": self.b.round(6).tolist(), "n_updates": self.n_updates}

    @classmethod
    def from_dict(cls, d):
        return cls(d["A"], d["b"], d.get("n_updates", 0))


def train_policy(n_samples=20000, prior_strength=PRIOR_STRENGTH, seed=42, freq="default"):
    """Khởi động: hồi quy ridge phần thưởng tiên nghiệm trên trạng thái lấy mẫu, rồi thu nhỏ còn
    `prior_strength` lượt quan sát mỗi hành động để phản hồi thật đủ sức kéo chính sách đi."""
    freq = load_state_freq() if freq == "default" else freq
    rng = np.random.default_rng(seed)
    states = [sample_state(rng, freq) for _ in range(n_samples)]
    X = np.stack([state_vector(s) for s in states])
    model = LinearBandit()
    scale = prior_strength / n_samples
    for i, a in enumerate(ACTION_IDS):
        r = np.array([prior_reward(s, a) for s in states])
        model.A[i] += scale * X.T @ X
        model.b[i] += scale * X.T @ r
    return model


def evaluate_policy(model, n_eval=2000, seed=123, freq="default"):
    """Trên trạng thái mới (hạt giống khác lúc huấn luyện), so phần thưởng tiên nghiệm trung bình của
    chính sách với chọn ngẫu nhiên, luôn khuyên khám, và chọn tối ưu (cận trên)."""
    freq = load_state_freq() if freq == "default" else freq
    rng = np.random.default_rng(seed)
    out = {"policy": [], "random": [], "always_urgent": [], "oracle": []}
    for _ in range(n_eval):
        s = sample_state(rng, freq)
        rewards = [prior_reward(s, a) for a in ACTION_IDS]
        greedy = "urgent_eval" if is_urgent(s) else ACTION_IDS[int(np.argmax(model.predict(s)))]
        out["policy"].append(prior_reward(s, greedy))
        out["random"].append(float(np.mean(rewards)))
        out["always_urgent"].append(prior_reward(s, "urgent_eval"))
        out["oracle"].append(max(rewards))
    return {k: round(float(np.mean(v)), 3) for k, v in out.items()}


def save_policy(model, path=None, meta=None):
    path = Path(path or DEFAULT_POLICY_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"algorithm": "linear_contextual_bandit", "actions": list(ACTION_IDS),
               "features": list(FEATURE_NAMES), **model.to_dict(), **(meta or {})}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_policy(path=None):
    """Chính sách khởi động đã lưu; tệp cũ hoặc thiếu thì huấn luyện lại (vài giây)."""
    path = Path(path or DEFAULT_POLICY_PATH)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("algorithm") == "linear_contextual_bandit" and data.get("actions") == list(ACTION_IDS):
            return LinearBandit.from_dict(data)
    return train_policy()


# ---------- agent ----------

class RLAgent:
    """Chọn trọng tâm tư vấn (epsilon-greedy có mặt nạ an toàn), ghi quyết định, và học từ 👍/👎."""

    def __init__(self, prior=None, store=None, epsilon=DEFAULT_EPSILON, seed=None):
        self.prior = prior if prior is not None else load_policy()
        self.store = store
        self.epsilon = float(epsilon)
        self.rng = np.random.default_rng(seed)
        saved = store.load_rl_model() if store is not None else None
        self.model = LinearBandit.from_dict(saved) if saved else self.prior.copy()

    @property
    def version(self):
        return f"prior+{self.model.n_updates}"

    def q_values(self, rl_state):
        scores = self.model.predict(rl_state)
        prev = rl_state.get("prev_action")
        if prev in ACTION_IDS and prev != "urgent_eval":
            scores = scores.copy()
            scores[ACTION_IDS.index(prev)] -= REPEAT_PENALTY
        return scores

    def recommend(self, state):
        s = extract_rl_state(state) if hasattr(state, "profile") else dict(state)
        scores = self.q_values(s)
        order = [int(i) for i in np.argsort(-scores)]
        k = len(ACTION_IDS)
        if is_urgent(s):
            idx, propensity, explored, mode = ACTION_IDS.index("urgent_eval"), 1.0, False, "mặt nạ an toàn"
        else:
            greedy = order[0]
            explored = bool(self.epsilon > 0 and self.rng.random() < self.epsilon)
            idx = int(self.rng.integers(0, k)) if explored else greedy
            propensity = (1 - self.epsilon + self.epsilon / k) if idx == greedy else self.epsilon / k
            explored = explored and idx != greedy
            mode = "thăm dò" if explored else "khai thác"
        action = ACTION_IDS[idx]
        return {
            "action": action,
            "label": ACTION_LABELS[action],
            "guidance": ACTION_GUIDANCE[action],
            "q_value": round(float(scores[idx]), 2),
            "ranking": [(ACTION_IDS[i], round(float(scores[i]), 2)) for i in order[:3]],
            "propensity": round(float(propensity), 4),
            "explored": explored,
            "mode": mode,
            "policy_version": self.version,
            "state": dict(s),
            "state_key": state_key(s),
        }

    def record(self, rl, session_id=None, run_id=None):
        """Ghi một quyết định vào SQLite (chờ phản hồi). Trả về id sự kiện, hoặc None khi không có store."""
        if self.store is None or not rl:
            return None
        return self.store.add_rl_event(session_id, run_id, rl)

    def update(self, rl_state, action, reward):
        """Học từ một phần thưởng: trả về thay đổi của điểm hành động đó ở trạng thái này."""
        before = float(self.model.predict(rl_state)[ACTION_IDS.index(action)])
        self.model.update(rl_state, action, reward)
        after = float(self.model.predict(rl_state)[ACTION_IDS.index(action)])
        return round(after - before, 4)

    def feedback(self, event_id, value):
        """Người dùng chấm trọng tâm của một lượt: value là 'up'/'down' hoặc số trong [-1, 1].
        Mỗi sự kiện chỉ được học một lần; trả về None nếu đã chấm rồi."""
        reward = FEEDBACK_REWARD[value] if isinstance(value, str) else float(np.clip(value, -1, 1))
        ev = self.store.rate_rl_event(event_id, reward)
        if ev is None:
            return None
        delta = self.update(ev["state"], ev["action"], reward)
        self.store.save_rl_model(self.model.to_dict())
        return {"event_id": event_id, "action": ev["action"], "reward": reward, "delta": delta,
                "policy_version": self.version}


def format_rl(rl):
    """Khối ngữ cảnh định hướng từ RLAgent gửi cho Advisor."""
    if not rl or not rl.get("action"):
        return ""
    return (f"Định hướng tư vấn cá nhân hóa [rl_policy] (agent học tăng cường, điểm {rl['q_value']:+.2f}):\n"
            f"- Trọng tâm ưu tiên: {rl['label']}. {rl['guidance']}")


# ---------- đánh giá ngoài chính sách trên phản hồi thật ----------

def off_policy_report(events, model):
    """events: các sự kiện đã chấm {state, action, propensity, reward}. Ước lượng phần thưởng của chính sách
    tham lam hiện tại bằng IPS và SNIPS (Swaminathan & Joachims 2015), so với phần thưởng đã ghi nhận."""
    rated = [e for e in events if e.get("reward") is not None]
    by_action = {}
    for e in rated:
        by_action.setdefault(e["action"], []).append(e["reward"])
    out = {"n_events": len(events), "n_rated": len(rated),
           "by_action": {a: {"n": len(v), "mean_reward": round(float(np.mean(v)), 3)} for a, v in by_action.items()}}
    if not rated:
        return out | {"logged_mean_reward": None, "ips": None, "snips": None}
    w, wr = [], []
    for e in rated:
        s = e["state"]
        target = "urgent_eval" if is_urgent(s) else ACTION_IDS[int(np.argmax(model.predict(s)))]
        match = 1.0 if e["action"] == target else 0.0
        w.append(match / max(e["propensity"], 1e-6))
        wr.append(w[-1] * e["reward"])
    return out | {"logged_mean_reward": round(float(np.mean([e["reward"] for e in rated])), 3),
                  "ips": round(float(np.mean(wr)), 3),
                  "snips": round(float(np.sum(wr) / np.sum(w)), 3) if np.sum(w) > 0 else None}
