"""Tính phân bố trạng thái RL thật từ BRFSS 2015 và chủ đề câu hỏi từ bộ ca benchmark.

Ghi ra kb/rl/brfss_state_freq.json (vài KB, nằm trong repo) để huấn luyện khởi động chính sách RL
mà không cần tệp CSV 13,5 MB, kể cả khi chạy test hay trên Kaggle.

- Phần hồ sơ (mức nguy cơ, thừa cân, ít vận động, tim mạch/hút thuốc) đếm trên 253.680 người BRFSS;
  mức nguy cơ lấy từ chính Predictor của hệ (bản đa nguồn đã hiệu chỉnh), giống lúc chạy thật.
- Chủ đề câu hỏi đếm trên các câu hỏi trong eval/cases.json, phân loại bằng rl.detect_topic.
- Mức xét nghiệm và "đã chẩn đoán" BRFSS không có, nên giữ là tỉ lệ giả định, ghi rõ trong tệp.

Chạy:  python tools/build_rl_states.py [đường_dẫn_csv]
Mặc định đọc ../diacare_datasets/brfss/cdc_diabetes_health_indicators.csv hoặc biến DIACARE_BRFSS.
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from diacare.predictor import Predictor  # noqa: E402
from diacare.rl import DEFAULT_STATE_FREQ, detect_topic, profile_flags  # noqa: E402
from diacare.rules import risk_band  # noqa: E402

DEFAULT_CSV = ROOT.parent / "diacare_datasets" / "brfss" / "cdc_diabetes_health_indicators.csv"

# BRFSS không có xét nghiệm hay chẩn đoán trong hồ sơ; đây là giả định, không phải số đo.
LAB_PRIOR = {"none": 0.45, "normal": 0.2, "prediabetes": 0.15, "diabetes": 0.15, "low": 0.05}
DIAGNOSED_PRIOR = 0.25


def risk_bands(pred, df):
    return [risk_band(float(v)) for v in pred.predict_many(df)]


def main():
    csv = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DIACARE_BRFSS") or DEFAULT_CSV)
    df = pd.read_csv(csv)
    pred = Predictor(ROOT / "models")
    df["band"] = risk_bands(pred, df)
    rows = df.to_dict("records")
    combos = Counter()
    for r in rows:
        f = profile_flags(r)
        combos[(r["band"], f["overweight"], f["inactive"], f["cardio_smoke"])] += 1
    cases = json.loads((ROOT / "eval" / "cases.json").read_text(encoding="utf-8"))
    questions = [c["q"] if "q" in c else c["turns"][-1] for c in cases]
    topics = Counter(detect_topic(q if isinstance(q, str) else q.get("q") or q.get("content", "")) for q in questions)
    out = {
        "source": f"BRFSS 2015 ({len(df)} người), mức nguy cơ từ Predictor; chủ đề từ eval/cases.json "
                  f"({len(cases)} câu hỏi)",
        "n": int(len(df)),
        "profiles": [{"band": b, "overweight": bool(o), "inactive": bool(i), "cardio_smoke": bool(c), "n": int(n)}
                     for (b, o, i, c), n in sorted(combos.items(), key=lambda kv: -kv[1])],
        "topics": {t: round(n / len(cases), 4) for t, n in sorted(topics.items())},
        "lab_prior": LAB_PRIOR,
        "diagnosed_prior": DIAGNOSED_PRIOR,
        "note": "lab_prior và diagnosed_prior là giả định (BRFSS không có xét nghiệm, chẩn đoán trong hồ sơ).",
    }
    path = DEFAULT_STATE_FREQ
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    bands = Counter(df["band"])
    print("wrote", path, "| profiles:", len(out["profiles"]), "| bands:", dict(bands), "| topics:", out["topics"])


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    np.set_printoptions(precision=3)
    main()
