"""Tạo dữ liệu GIẢ cho agent Q-learning (diacare.coach), huấn luyện, đánh giá, và (tùy chọn) nạp vào một DB demo.

1. 30 người bệnh mô phỏng (diacare.coach_sim), mỗi người theo dõi 14–28 ngày. Lời nhắc mỗi sáng do chính sách
   sinh dữ liệu chọn: 60% ngẫu nhiên đều, 40% theo luật, có ghi xác suất chọn.
2. Học bảng Q ngoài chính sách (off-policy) từ đúng các ngày đó: gamma 0,9 (Q-learning) và gamma 0 (bandit).
3. Đánh giá trên 200 người bệnh mô phỏng MỚI (hạt giống khác), so với luật cố định và chọn ngẫu nhiên.

Đầu ra (cùng hạt giống thì ra đúng như cũ):
  data/rl_demo/patients.json, readings.csv, decisions.csv, eval.json   dữ liệu giả và kết quả
  models/q_coach.json                                                   bảng Q gamma 0,9 dùng trong ứng dụng
  data/rl_demo/demo.db   (khi có --db)                                   30 người bệnh để demo trên giao diện

    python tools/make_rl_demo_data.py --db
"""
import argparse
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from diacare.coach import DEFAULT_COACH_PATH, QCoach, save_coach  # noqa: E402
from diacare.coach_sim import (behavior_policy, coach_policy, evaluate, make_patients, paired_diff,  # noqa: E402
                               random_policy, rule_policy, run_episode)
from diacare.samples import HIGH_RISK  # noqa: E402

import numpy as np  # noqa: E402

OUT = ROOT / "data" / "rl_demo"
END = date(2026, 11, 23)  # ngày theo dõi cuối của mọi người; mỗi người bắt đầu sớm hơn tùy số ngày
WARMUP = 3
START = END - timedelta(days=28 + WARMUP - 1)  # mốc cho người bệnh mô phỏng lúc đánh giá


def profile_for(t):
    """Hồ sơ BRFSS khớp đặc điểm mô phỏng (chỉ để giao diện có hồ sơ; agent Q-learning không dùng)."""
    p = dict(HIGH_RISK)
    p["BMI"] = 31 if "thừa cân" in t["issues"] else 24
    p["PhysActivity"] = 0 if "ít vận động" in t["issues"] else 1
    p["HighBP"] = p["HighChol"] = p["Smoker"] = 1 if "tim mạch" in t["issues"] else 0
    p["HeartDiseaseorAttack"] = 0
    p["Sex"] = 1 if t["sex"] == "nam" else 0
    p["Age"] = int(np.clip((t["age"] - 18) // 5 + 1, 1, 13))
    return p


def flat_state(s, prefix):
    return {f"{prefix}adherence": s["adherence"], f"{prefix}control": s["control"], f"{prefix}prev": s["prev"],
            f"{prefix}urgent": int(s["urgent"])} if s else {f"{prefix}{k}": "" for k in
                                                           ("adherence", "control", "prev", "urgent")}


def write_demo_db(path, patients, readings_by_code, steps_by_code):
    from diacare.db import Store
    if path.exists():
        path.unlink()
    store = Store(str(path))
    for t in patients:
        pid = store.save_patient(t["name"], profile_for(t))
        store.add_memory(pid, "diagnosis", "đái tháo đường típ 2")
        for r in readings_by_code[t["code"]]:
            store.add_reading(pid, r["kind"], r["value"], r["measured_at"], unit="mg/dL", context=r["context"],
                              note="dữ liệu mô phỏng")
        steps = steps_by_code[t["code"]]
        for st in steps:
            store.add_coach_event(pid, st["day"], st)
        for st in steps[:-1]:
            # các ngày này đã dùng để huấn luyện bảng Q có sẵn: đánh dấu đã học để bước học tiếp không học lại.
            # Ngày cuối để dành: mở tab Hôm nay của người đó thì agent học tiếp ngày này (demo học trực tuyến).
            store.mark_coach_learned(pid, st["day"], st["reward"])
        last = date.fromisoformat(steps_by_code[t["code"]][-1]["day"])
        store.set_appointment(pid, (last + timedelta(days=10)).isoformat(), place="Phòng khám nội tiết (mẫu)")
    store.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--db", action="store_true", help="nạp 30 người bệnh vào data/rl_demo/demo.db")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    patients = make_patients(args.n, seed=args.seed)
    rng = np.random.default_rng(args.seed)
    behavior = behavior_policy(0.6)
    readings_by_code, steps_by_code, transitions = {}, {}, []
    for t in patients:
        start = END - timedelta(days=t["days"] + WARMUP - 1)
        readings, steps = run_episode(t, behavior, start, rng, warmup=WARMUP)
        readings_by_code[t["code"]], steps_by_code[t["code"]] = readings, steps
        transitions += steps[:-1]  # ngày cuối của mỗi người để dành cho bước học tiếp trong ứng dụng

    (OUT / "patients.json").write_text(json.dumps(patients, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(OUT / "readings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "measured_at", "kind", "context", "value_mgdl"])
        for code, rows in readings_by_code.items():
            for r in rows:
                w.writerow([code, r["measured_at"], r["kind"], r["context"], r["value"]])
    with open(OUT / "decisions.csv", "w", newline="", encoding="utf-8") as f:
        fields = ["code", "day", "s_adherence", "s_control", "s_prev", "s_urgent", "action", "propensity", "mode",
                  "reward", "n_adherence", "n_control", "n_prev", "n_urgent", "train"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for steps in steps_by_code.values():
            for i, st in enumerate(steps):
                w.writerow({"code": st["code"], "day": st["day"], **flat_state(st["state"], "s_"),
                            "action": st["action"], "propensity": st["propensity"], "mode": st["mode"],
                            "reward": st["reward"], **flat_state(st["next_state"], "n_"),
                            "train": int(i < len(steps) - 1)})

    data_meta = {"source": "dữ liệu mô phỏng (diacare.coach_sim), không phải người thật", "patients": len(patients),
                 "transitions": len(transitions), "seed": args.seed, "behavior_epsilon": 0.6}
    q = QCoach(gamma=0.9, meta=data_meta)
    q.fit(transitions)
    bandit = QCoach(gamma=0.0, meta=data_meta)
    bandit.fit(transitions)
    save_coach(q, DEFAULT_COACH_PATH)

    test = make_patients(200, seed=args.seed + 1000)
    results = {
        "Q-learning (gamma 0,9)": evaluate(coach_policy(q), test, START, seed=99),
        "Bandit (gamma 0)": evaluate(coach_policy(bandit), test, START, seed=99),
        "Luật cố định": evaluate(rule_policy, test, START, seed=99),
        "Ngẫu nhiên": evaluate(random_policy, test, START, seed=99),
    }
    qr = results["Q-learning (gamma 0,9)"]["returns"]
    paired = {f"Q-learning - {name}": paired_diff(qr, r["returns"]) for name, r in results.items()
              if not name.startswith("Q-learning")}
    for r in results.values():
        r.pop("returns")
    report = {"data": data_meta, "coverage": q.coverage(), "paired_difference": paired,
              "logged_mean_reward": round(float(np.mean([s["reward"] for s in transitions])), 3),
              "eval_on_new_simulated_patients": results,
              "note": "Đánh giá trên người bệnh mô phỏng mới, 21 ngày mỗi người. Động lực do nhóm tự đặt."}
    (OUT / "eval.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.db:
        write_demo_db(OUT / "demo.db", patients, readings_by_code, steps_by_code)

    print(f"{len(patients)} người bệnh, {sum(len(v) for v in steps_by_code.values())} ngày có lời nhắc "
          f"({len(transitions)} ngày dùng để huấn luyện sẵn), "
          f"{sum(len(v) for v in readings_by_code.values())} số đo đường huyết")
    print("Độ phủ:", q.coverage())
    for name, r in results.items():
        print(f"{name:24s} tổng thưởng TB {r['mean_return']:7.2f} {r['ci95']}  ngày có đo {r['logged_days']:.2f}"
              f"  số đo đạt {r['in_target']:.2f}")
    for name, d in paired.items():
        print(f"{name:34s} chênh từng người {d['mean']:+.2f} {d['ci95']}")


if __name__ == "__main__":
    main()
