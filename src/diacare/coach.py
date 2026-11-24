r"""Agent học tăng cường Q-learning: chọn lời nhắc mỗi ngày cho người đã chẩn đoán đái tháo đường típ 2.

Vì sao Q-learning ở đây mà không phải bandit: lời nhắc hôm nay làm đổi hành vi ngày mai. Nhắc đo đường huyết đều
thì người bệnh dần có thói quen ghi nhật ký, và khi đã có thói quen thì lời khuyên về ăn uống, vận động mới có
tác dụng. Tức là có bước chuyển trạng thái $s_t \to s_{t+1}$ thật, và hệ số chiết khấu $\gamma > 0$ có ý nghĩa.
(Bộ chọn trọng tâm trong khung chat, diacare.rl, là trường hợp $\gamma = 0$: mỗi lượt hỏi là một bài toán riêng.)

Bài toán (Sutton & Barto, ch. 6.5, Q-learning):
- Mỗi sáng, agent nhìn trạng thái $s$ tính từ nhật ký 3 ngày trước đó và chọn một trong 6 trọng tâm nhắc $a$
  (dùng chung 6 trọng tâm an toàn của diacare.rl).
- Phần thưởng $r$ tính hoàn toàn từ nhật ký của chính ngày đó: có đo hay không, chỉ số đạt mục tiêu hay không,
  có hạ đường huyết không. Không cần người dùng bấm 👍/👎; nếu có bấm thì cộng/trừ thêm R_FEEDBACK.
- Cập nhật: $Q(s,a) \leftarrow Q(s,a) + \alpha\,[r + \gamma \max_{a'} Q(s',a') - Q(s,a)]$.

Trạng thái gọn, 4 × 3 × 3 = 36 ô, để vài trăm ngày dữ liệu đủ phủ:
- đo đều: số ngày có ghi đường huyết trong 3 ngày qua: 0 → "ít", 1–2 → "vừa", 3 → "đều";
- kiểm soát: "chưa đo", "đạt" (≥ 70% số đo trong mục tiêu), "cao", "nguy hiểm" (có hạ đường huyết hoặc ≥ 250);
- nhóm lời nhắc hôm qua: "không", "theo dõi" (khám sớm, đo đường huyết), "lối sống" (4 trọng tâm còn lại).

An toàn:
1. Mặt nạ: hôm qua có hạ đường huyết hoặc chỉ số ≥ 250 mg/dL thì luôn chọn "khám sớm", không thăm dò.
2. Cả 6 hành động đều là lời khuyên an toàn có sẵn, không có hành động nào về thuốc.
3. Trạng thái và phần thưởng tính bằng chính các hàm phân loại của diacare.journal (mục tiêu ADA 2024 hoặc mục
   tiêu bác sĩ đặt), nên agent chạy được trên nhật ký thật y như trên dữ liệu mô phỏng.
"""
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from diacare.journal import classify_glucose, resolve_targets, to_vn
from diacare.rl import ACTION_IDS, ACTION_LABELS

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_COACH_PATH = ROOT / "models" / "q_coach.json"

ADHERENCE = ("ít", "vừa", "đều")
CONTROL = ("chưa đo", "đạt", "cao", "nguy hiểm")
PREV_GROUP = ("không", "theo dõi", "lối sống")
STATES = tuple((a, c, p) for a in ADHERENCE for c in CONTROL for p in PREV_GROUP)
_MONITOR = ("urgent_eval", "glycemic_followup")
# "Khám sớm" chỉ do mặt nạ an toàn chọn. Bản đầu cho agent tự chọn thì nó học dùng "khám sớm" như một cách thúc
# người bệnh đo, cả khi chỉ số bình thường: làm người bệnh lo vô cớ.
CHOICES = tuple(a for a in ACTION_IDS if a != "urgent_eval")
WINDOW_DAYS = 3

# Phần thưởng: bỏ đo phải tệ hơn MỌI kết quả đo, kể cả hạ đường huyết. Không đo thì không thấy hạ đường huyết; nếu
# đo thấy hạ bị phạt nặng hơn bỏ đo, agent sẽ học cách làm người dễ hạ đường huyết bớt đo, tức là che giấu nó.
# Thứ tự: bỏ đo (-1) < đo thấy hạ mức 2 (-0,9) < hạ mức 1 (-0,5) < rất cao (0) < cao (0,7) < đạt (1,5).
R_LOGGED, R_MISSED = 1.0, -1.0
R_READING = {"in_target": 0.5, "below_target": 0.0, "above_target": -0.3, "very_high": -1.0,
             "hypo_1": -1.5, "hypo_2": -1.9}
R_REPEAT = -0.3  # nhắc lại đúng một lời hai ngày liền: người bệnh nhàm
# 👍/👎 của người bệnh cho lời nhắc (không bắt buộc): chỉ là phần thưởng phụ, nhỏ hơn khoảng cách giữa bỏ đo và có đo
# (2,0), để một cú 👎 không dạy agent rằng thà người bệnh bỏ đo còn hơn.
R_FEEDBACK = 0.3

ALPHA, GAMMA, EPOCHS = 0.1, 0.9, 200

# Lời nhắc hiện cho người bệnh, giọng tự nhiên. Không có câu nào về liều thuốc.
NUDGES = {
    "urgent_eval": ("Hôm qua có chỉ số đường huyết đáng lo. Bạn đo lại sáng nay nhé, và nếu vẫn bất thường "
                    "thì gọi cho bác sĩ hoặc đi khám sớm, đừng đợi tới lịch hẹn."),
    "glycemic_followup": ("Sáng nay bạn nhớ đo đường huyết lúc đói rồi ghi vào nhật ký nhé. Đo đều vài ngày liền "
                          "sẽ giúp bạn và bác sĩ thấy rõ xu hướng hơn là một con số lẻ."),
    "weight_diet": ("Hôm nay thử chia bữa trưa thành nửa đĩa rau, một phần tư đạm, một phần tư cơm nhé. "
                    "Bớt nửa bát cơm trắng là đường huyết sau ăn đã dễ chịu hơn nhiều."),
    "physical_activity": ("Sau bữa tối hôm nay, bạn thử đi bộ nhẹ 15–20 phút nhé. Vận động ngay sau ăn giúp "
                          "đường huyết sau ăn hạ xuống rõ rệt."),
    "cardio_control": ("Hôm nay bạn để ý giúp mình: ăn nhạt hơn một chút, và nếu đang hút thuốc thì thử bớt "
                       "một điếu. Giữ huyết áp và mỡ máu ổn cũng là bảo vệ tim của bạn."),
    "preventive_habit": ("Mấy ngày nay bạn giữ nếp tốt lắm. Hôm nay cứ duy trì như vậy: ăn đủ rau, đi lại "
                         "nhẹ nhàng, ngủ đủ giấc."),
}


def _day(r):
    return to_vn(r["measured_at"]).date()


def _glucose_by_day(readings):
    out = {}
    for r in readings:
        if r["kind"] == "glucose":
            out.setdefault(_day(r), []).append(r)
    return out


def reading_levels(rows, targets=None):
    t = resolve_targets(targets) if not isinstance(targets, dict) or "pre" not in targets else targets
    return [classify_glucose(r["value"], r.get("context"), t) for r in rows]


def prev_group(action):
    if not action:
        return "không"
    return "theo dõi" if action in _MONITOR else "lối sống"


def day_state(readings, day, prev_action=None, targets=None):
    """Trạng thái buổi sáng ngày `day`, tính từ nhật ký của 3 ngày trước đó (không dùng số đo của chính ngày đó)."""
    by_day = _glucose_by_day(readings)
    window = [day - timedelta(days=k) for k in range(1, WINDOW_DAYS + 1)]
    logged = sum(1 for d in window if by_day.get(d))
    adherence = "ít" if logged == 0 else ("đều" if logged == WINDOW_DAYS else "vừa")
    levels = [lv for d in window for lv in reading_levels(by_day.get(d, []), targets)]
    if not levels:
        control = "chưa đo"
    elif any(lv in ("hypo_1", "hypo_2", "very_high") for lv in levels):
        control = "nguy hiểm"
    elif sum(lv == "in_target" for lv in levels) >= 0.7 * len(levels):
        control = "đạt"
    else:
        control = "cao"
    yesterday = reading_levels(by_day.get(day - timedelta(days=1), []), targets)
    urgent = any(lv in ("hypo_1", "hypo_2", "very_high") for lv in yesterday)
    return {"adherence": adherence, "control": control, "prev": prev_group(prev_action), "urgent": urgent,
            "prev_action": prev_action}


def state_index(s):
    return STATES.index((s["adherence"], s["control"], s["prev"]))


def day_reward(readings, day, action, prev_action=None, targets=None, feedback=None):
    """Phần thưởng của lời nhắc ngày `day`, tính từ nhật ký của chính ngày đó; `feedback` (+1/-1) nếu người bệnh đã
    bấm 👍/👎 cho lời nhắc đó."""
    rows = _glucose_by_day(readings).get(day, [])
    if not rows:
        r = R_MISSED
    else:
        r = R_LOGGED + float(np.mean([R_READING[lv] for lv in reading_levels(rows, targets)]))
    if prev_action and action == prev_action and action != "urgent_eval":
        r += R_REPEAT
    if feedback:
        r += R_FEEDBACK * (1 if feedback > 0 else -1)
    return round(r, 4)


class QCoach:
    """Bảng Q 36 × 6, học ngoài chính sách (off-policy) từ các ngày đã ghi."""

    def __init__(self, q=None, counts=None, gamma=GAMMA, meta=None):
        self.q = np.zeros((len(STATES), len(ACTION_IDS))) if q is None else np.asarray(q, dtype=float)
        self.counts = np.zeros_like(self.q, dtype=int) if counts is None else np.asarray(counts, dtype=int)
        self.gamma = float(gamma)
        self.meta = meta or {}

    def fit(self, transitions, alpha=ALPHA, epochs=EPOCHS, seed=0):
        """transitions: [{state, action, reward, next_state (None nếu là ngày cuối)}]. Quét lại nhiều lượt theo
        thứ tự ngẫu nhiên (experience replay dạng bảng). Trả về độ thay đổi lớn nhất của Q ở lượt quét cuối."""
        rng = np.random.default_rng(seed)
        items = [(state_index(t["state"]), ACTION_IDS.index(t["action"]), float(t["reward"]),
                  None if t.get("next_state") is None else state_index(t["next_state"])) for t in transitions]
        for s, a, _, _ in items:
            self.counts[s, a] += 1
        delta = 0.0
        for _ in range(epochs):
            delta = 0.0
            for i in rng.permutation(len(items)):
                s, a, r, s2 = items[i]
                target = r + (self.gamma * self.q[s2].max() if s2 is not None else 0.0)
                step = alpha * (target - self.q[s, a])
                self.q[s, a] += step
                delta = max(delta, abs(step))
        return delta

    def update(self, s, action, reward, next_state, alpha=ALPHA):
        """Một bước Q-learning trực tuyến cho một ngày đã kết thúc. Trả về độ thay đổi của Q(s, a)."""
        i, a = state_index(s), ACTION_IDS.index(action)
        target = reward + (self.gamma * self.q[state_index(next_state)].max() if next_state is not None else 0.0)
        step = alpha * (target - self.q[i, a])
        self.q[i, a] += step
        self.counts[i, a] += 1
        self.meta["online_updates"] = int(self.meta.get("online_updates", 0)) + 1
        return round(float(step), 4)

    def copy(self):
        return QCoach.from_dict(json.loads(json.dumps(self.to_dict())))

    def scores(self, s):
        return self.q[state_index(s)].copy()

    def act(self, s, epsilon=0.0, rng=None):
        """(hành động, xác suất chọn, chế độ). Mặt nạ an toàn trước, rồi epsilon-greedy."""
        if s.get("urgent"):
            return "urgent_eval", 1.0, "mặt nạ an toàn"
        q = self.scores(s)
        allowed = np.array([a in CHOICES for a in ACTION_IDS])
        seen = (self.counts[state_index(s)] > 0) & allowed
        q = np.where(seen if seen.any() else allowed, q, -np.inf)  # chỉ khai thác hành động đã có dữ liệu
        greedy = int(np.argmax(q))
        k = len(CHOICES)
        if epsilon > 0 and rng is not None and rng.random() < epsilon:
            idx = ACTION_IDS.index(CHOICES[int(rng.integers(0, k))])
        else:
            idx = greedy
        p = (1 - epsilon + epsilon / k) if idx == greedy else epsilon / k
        return ACTION_IDS[idx], round(float(p), 4), ("khai thác" if idx == greedy else "thăm dò")

    def coverage(self):
        """Tỉ lệ ô (trạng thái, hành động) có dữ liệu, và số trạng thái đã gặp."""
        return {"cells_seen": int((self.counts > 0).sum()), "cells_total": int(self.counts.size),
                "states_seen": int((self.counts.sum(axis=1) > 0).sum()), "states_total": len(STATES)}

    def to_dict(self):
        return {"states": ["|".join(s) for s in STATES], "actions": list(ACTION_IDS), "gamma": self.gamma,
                "q": np.round(self.q, 4).tolist(), "counts": self.counts.tolist(), "meta": self.meta}

    @classmethod
    def from_dict(cls, d):
        return cls(q=d["q"], counts=d["counts"], gamma=d.get("gamma", GAMMA), meta=d.get("meta"))


def save_coach(coach, path=DEFAULT_COACH_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(coach.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_coach(path=DEFAULT_COACH_PATH):
    path = Path(path)
    return QCoach.from_dict(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None


MODEL_TABLE = "coach_model"  # bảng Q đã học tiếp (rl_model là của bandit trong khung chat)


def _as_date(day):
    return day if isinstance(day, date) else date.fromisoformat(str(day)[:10])


def coach_from_store(store, prior):
    """Bảng Q đang dùng: bản đã học tiếp lưu trong DB, chưa có thì bản huấn luyện sẵn (models/q_coach.json)."""
    saved = store.load_rl_model(table=MODEL_TABLE)
    return QCoach.from_dict(saved) if saved else prior.copy()


def learn_from_journal(store, prior, patient_id, today):
    """Học tiếp từ những ngày đã kết thúc của một người bệnh (trước `today`) mà chưa học.

    Với mỗi ngày đã nhắc: phần thưởng tính từ nhật ký của ngày đó, trạng thái kế tiếp là trạng thái sáng hôm sau
    tính từ nhật ký (dù người bệnh có mở ứng dụng hôm sau hay không), rồi một bước Q-learning. Mỗi ngày chỉ học
    một lần (cột learned_reward), dưới khoá để hai phiên mở cùng lúc không học trùng.
    Trả về danh sách {day, action, reward, delta}."""
    today = _as_date(today)
    pending = [ev for ev in store.coach_events(patient_id)
               if ev["learned_reward"] is None and _as_date(ev["day"]) < today]
    if not pending:
        return []
    readings = store.list_readings(patient_id)
    targets = store.get_targets(patient_id)
    by_day = {_as_date(ev["day"]): ev["action"] for ev in store.coach_events(patient_id)}
    out = []
    with store.exclusive("coach-model"):
        coach = coach_from_store(store, prior)
        for ev in pending:
            day = _as_date(ev["day"])
            prev = by_day.get(day - timedelta(days=1))
            reward = day_reward(readings, day, ev["action"], prev, targets, ev.get("feedback"))
            if not store.mark_coach_learned(patient_id, day, reward):
                continue  # phiên khác vừa học ngày này
            nxt = day_state(readings, day + timedelta(days=1), ev["action"], targets)
            delta = coach.update(ev["state"], ev["action"], reward, nxt)
            out.append({"day": str(day), "action": ev["action"], "reward": reward, "delta": delta})
        if out:
            store.save_rl_model(coach.to_dict(), table=MODEL_TABLE)
    return out


def daily_nudge(store, prior, patient_id, today):
    """Lời nhắc hôm nay của một người bệnh: trước hết học tiếp từ những ngày đã qua, rồi chọn một lần mỗi ngày,
    ghi vào bảng coach_events; mở lại trong ngày thì giữ nguyên. Lời nhắc hôm qua là `prev_action` của trạng
    thái hôm nay. `prior`: bảng Q huấn luyện sẵn, dùng khi DB chưa có bản học tiếp."""
    learned = learn_from_journal(store, prior, patient_id, today)
    coach = coach_from_store(store, prior)
    done = store.coach_events(patient_id, day=today)
    if done:
        ev = done[-1]
        return {**ev, "label": ACTION_LABELS[ev["action"]], "text": NUDGES[ev["action"]], "learned": learned,
                "ranking": sorted(zip(ACTION_IDS, coach.scores(ev["state"])), key=lambda x: -x[1])[:3]}
    yesterday = store.coach_events(patient_id, day=today - timedelta(days=1))
    prev = yesterday[-1]["action"] if yesterday else None
    nudge = today_nudge(coach, store.list_readings(patient_id), today, prev, store.get_targets(patient_id))
    store.add_coach_event(patient_id, today, nudge)
    return {**nudge, "learned": learned}


def history_rewards(store, patient_id, targets=None, today=None):
    """Các ngày đã nhắc kèm phần thưởng tính lại từ nhật ký. Từ `today` trở đi chưa hết ngày nên bỏ."""
    readings = store.list_readings(patient_id)
    events = store.coach_events(patient_id)
    by_day = {_as_date(ev["day"]): ev["action"] for ev in events}
    out = []
    for ev in events:
        day = _as_date(ev["day"])
        if today is not None and day >= _as_date(today):
            break
        prev = by_day.get(day - timedelta(days=1))
        out.append({**ev, "reward": day_reward(readings, day, ev["action"], prev, targets, ev.get("feedback"))})
    return out


def today_nudge(coach, readings, today, prev_action=None, targets=None):
    """Lời nhắc cho buổi sáng `today` từ nhật ký thật của người bệnh."""
    s = day_state(readings, today, prev_action, targets)
    action, propensity, mode = coach.act(s)
    ranking = sorted(zip(ACTION_IDS, coach.scores(s)), key=lambda x: -x[1])[:3]
    return {"action": action, "label": ACTION_LABELS[action], "text": NUDGES[action], "state": s, "mode": mode,
            "propensity": propensity, "ranking": [(a, round(float(v), 2)) for a, v in ranking]}
