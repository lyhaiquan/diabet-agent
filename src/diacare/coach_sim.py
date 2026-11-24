"""Người bệnh mô phỏng để tạo dữ liệu và đánh giá agent Q-learning (diacare.coach). DỮ LIỆU GIẢ, không phải người thật.

Mỗi người bệnh có vài đặc điểm ẩn, agent không nhìn thấy:
- `base_log`: mức chịu khó đo đường huyết vốn có; `habit`: thói quen ghi nhật ký, tăng khi đo, giảm khi bỏ đo;
- `mu`: đường huyết lúc đói trung bình (mg/dL) khi chưa thay đổi lối sống;
- `issues`: vấn đề chính (thừa cân, ít vận động, tim mạch), quyết định lời nhắc lối sống nào có tác dụng;
- `hypo_prone`: người dễ hạ đường huyết (vd đang dùng insulin hoặc sulfonylurea).

Động lực do nhóm tự đặt, nên mọi kết quả trên mô phỏng chỉ cho thấy agent học được đúng quy luật đã cài vào đây:
1. Nhắc đo đường huyết làm tăng khả năng đo hôm đó, nên thói quen tăng dần qua các ngày.
2. Lời nhắc lối sống chỉ có tác dụng nếu đúng vấn đề của người đó, và tác dụng nhân với thói quen (người đã quen
   theo dõi thì làm theo lời khuyên nhiều hơn). Đây là chỗ hành động hôm nay ảnh hưởng tới ngày mai, nên
   chính sách nhìn xa ($\\gamma > 0$) được lợi so với chính sách chỉ nhìn một ngày. Lợi thế đó một phần do cách đặt
   động lực, phải nói rõ khi báo cáo.
3. Nhắc lại đúng một lời hai ngày liền thì tác dụng giảm một nửa.
4. Sau khi có chỉ số nguy hiểm mà được nhắc đi khám, nguy cơ hạ đường huyết các ngày sau giảm.
"""
from datetime import datetime, time, timedelta

import numpy as np

from diacare.coach import CHOICES, day_reward, day_state
from diacare.journal import VN_TZ

ISSUE_ACTION = {"thừa cân": "weight_diet", "ít vận động": "physical_activity", "tim mạch": "cardio_control"}
FAMILY = ("Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi", "Đỗ", "Ngô")


def make_patients(n, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        k = rng.integers(1, 3)
        issues = sorted(rng.choice(list(ISSUE_ACTION), size=k, replace=False).tolist())
        out.append({
            "code": f"BN{i + 1:02d}",
            "name": f"Bệnh nhân mẫu {i + 1:02d} ({FAMILY[i % len(FAMILY)]})",
            "age": int(rng.integers(42, 75)),
            "sex": "nam" if rng.random() < 0.5 else "nữ",
            "days": int(rng.integers(14, 29)),
            "base_log": round(float(rng.uniform(0.25, 0.85)), 2),
            "habit": round(float(rng.uniform(0.1, 0.5)), 2),
            "mu": round(float(rng.uniform(115, 175)), 1),
            "issues": issues,
            "hypo_prone": bool(rng.random() < 0.25),
        })
    return out


def _at(day, hh, mm):
    return datetime.combine(day, time(hh, mm), tzinfo=VN_TZ).isoformat()


class SimPatient:
    def __init__(self, traits, start, rng):
        self.t = dict(traits)
        self.rng = rng
        self.start = start
        self.habit = traits["habit"]
        self.life = 0.0      # mức thay đổi lối sống tích lũy, 0..1
        self.safe_days = 0   # số ngày còn được bác sĩ chỉnh sau khi khám vì chỉ số nguy hiểm
        self.readings = []

    def _glucose(self, context):
        mu = self.t["mu"] - 45 * self.life
        if context == "after_meal":
            mu += 45
        v = mu + self.rng.normal(0, 18)
        if self.t["hypo_prone"] and self.safe_days == 0 and self.rng.random() < 0.06 + 0.06 * self.life:
            v = self.rng.uniform(52, 68)
        return float(np.clip(v, 45, 380))

    def live_day(self, day, action=None, prev_action=None):
        """Một ngày sống sau lời nhắc `action` buổi sáng: có thể đo 1–2 lần. Trả về số đo của ngày."""
        fatigue = 0.5 if action and action == prev_action else 1.0
        boost = 0.0
        if action == "glycemic_followup":
            boost = 0.30 * fatigue
        elif action == "preventive_habit":
            boost = 0.08 * fatigue
        elif action == "urgent_eval":
            boost = 0.15 * fatigue
        p_log = float(np.clip(0.45 * self.t["base_log"] + 0.45 * self.habit + boost, 0.02, 0.97))
        if action in ISSUE_ACTION.values():
            hit = any(ISSUE_ACTION[i] == action for i in self.t["issues"])
            self.life += (0.10 if hit else 0.01) * fatigue * (0.3 + 0.7 * self.habit) * (1 - self.life)
        elif action == "preventive_habit":
            self.life += 0.02 * fatigue * (1 - self.life)
        self.life = max(0.0, self.life - 0.01)  # không nhắc thì dần quên
        if action == "urgent_eval":
            last = self.readings[-3:]
            if any(r["value"] < 70 or r["value"] >= 250 for r in last):
                self.safe_days = 7
        rows = []
        if self.rng.random() < p_log:
            rows.append({"kind": "glucose", "value": round(self._glucose("fasting")), "context": "fasting",
                         "unit": "mg/dL", "measured_at": _at(day, 6, int(self.rng.integers(0, 50)))})
            if self.rng.random() < 0.5:
                rows.append({"kind": "glucose", "value": round(self._glucose("after_meal")), "context": "after_meal",
                             "unit": "mg/dL", "measured_at": _at(day, 13, int(self.rng.integers(0, 50)))})
            self.habit += 0.12 * (1 - self.habit)
        else:
            self.habit = max(0.0, self.habit - 0.06)
        self.safe_days = max(0, self.safe_days - 1)
        self.readings += rows
        return rows


def run_episode(traits, policy, start, rng, warmup=3, days=None):
    """policy(state, rng) -> (action, propensity, mode). Trả về (số đo, các bước chuyển)."""
    p = SimPatient(traits, start, rng)
    for k in range(warmup):  # vài ngày đầu chưa có lời nhắc, để có trạng thái ban đầu
        p.live_day(start + timedelta(days=k))
    steps, prev = [], None
    n = days or traits["days"]
    for k in range(warmup, warmup + n):
        day = start + timedelta(days=k)
        s = day_state(p.readings, day, prev)
        action, prop, mode = policy(s, rng)
        p.live_day(day, action, prev)
        r = day_reward(p.readings, day, action, prev)
        steps.append({"code": traits["code"], "day": day.isoformat(), "state": s, "action": action,
                      "propensity": prop, "mode": mode, "reward": r})
        prev = action
    for i, st in enumerate(steps):  # trạng thái kế tiếp, ngày cuối là kết thúc
        st["next_state"] = steps[i + 1]["state"] if i + 1 < len(steps) else None
    return p.readings, steps


# ---- các chính sách để so sánh ----

def rule_policy(s, rng=None):
    """Luật cố định hợp lý: nguy hiểm thì khám, ít đo thì nhắc đo, còn lại xoay vòng lời khuyên lối sống."""
    if s.get("urgent"):
        return "urgent_eval", 1.0, "luật"
    if s["adherence"] != "đều":
        return "glycemic_followup", 1.0, "luật"
    if s["control"] == "đạt":
        return "preventive_habit", 1.0, "luật"
    return ("physical_activity" if s.get("prev_action") == "weight_diet" else "weight_diet"), 1.0, "luật"


def random_policy(s, rng):
    if s.get("urgent"):
        return "urgent_eval", 1.0, "mặt nạ an toàn"
    return CHOICES[int(rng.integers(0, len(CHOICES)))], round(1 / len(CHOICES), 4), "ngẫu nhiên"


def behavior_policy(epsilon=0.6):
    """Chính sách sinh dữ liệu: với xác suất epsilon chọn ngẫu nhiên đều, còn lại theo luật. Ghi đúng xác suất
    chọn để học và đánh giá ngoài chính sách (off-policy) là hợp lệ."""
    k = len(CHOICES)

    def policy(s, rng):
        if s.get("urgent"):
            return "urgent_eval", 1.0, "mặt nạ an toàn"
        greedy = rule_policy(s)[0]
        a = CHOICES[int(rng.integers(0, k))] if rng.random() < epsilon else greedy
        p = (1 - epsilon + epsilon / k) if a == greedy else epsilon / k
        return a, round(p, 4), ("luật" if a == greedy else "ngẫu nhiên")
    return policy


def coach_policy(coach):
    return lambda s, rng: coach.act(s)


def evaluate(policy, patients, start, seed, days=21):
    """Tổng phần thưởng mỗi người và tỉ lệ ngày có đo / số đo đạt mục tiêu, trên người bệnh mô phỏng."""
    rng = np.random.default_rng(seed)
    returns, logged, in_target = [], [], []
    for t in patients:
        readings, steps = run_episode(t, policy, start, rng, days=days)
        returns.append(sum(s["reward"] for s in steps))
        days_set = {s["day"] for s in steps}
        logged.append(sum(1 for d in days_set if any(r["measured_at"][:10] == d for r in readings)) / len(steps))
        rs = [r for r in readings if r["measured_at"][:10] in days_set]
        lv = [(80 <= r["value"] <= 130) if r["context"] == "fasting" else (70 <= r["value"] < 180) for r in rs]
        in_target.append(float(np.mean(lv)) if lv else 0.0)
    a = np.asarray(returns)
    half = 1.96 * a.std(ddof=1) / np.sqrt(len(a))
    return {"n": len(a), "mean_return": round(float(a.mean()), 2), "ci95": [round(float(a.mean() - half), 2),
            round(float(a.mean() + half), 2)], "logged_days": round(float(np.mean(logged)), 3),
            "in_target": round(float(np.mean(in_target)), 3), "returns": [round(float(x), 3) for x in a]}


def paired_diff(a, b):
    """Chênh tổng thưởng từng người (a - b) trên cùng nhóm người bệnh: trung bình và khoảng tin cậy 95%."""
    d = np.asarray(a) - np.asarray(b)
    half = 1.96 * d.std(ddof=1) / np.sqrt(len(d))
    return {"mean": round(float(d.mean()), 2), "ci95": [round(float(d.mean() - half), 2),
                                                         round(float(d.mean() + half), 2)]}
