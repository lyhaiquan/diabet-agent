"""Tính mức liên hệ giữa 21 chỉ số BRFSS 2015 và nhãn tiểu đường, ghi ra kb/graph/brfss_associations.json.

Đây là loại cạnh "tính từ dữ liệu" của đồ thị tri thức (diacare.kg). Kết quả nhỏ nên được lưu vào repo:
đồ thị dựng được mà không cần tệp CSV 13,5 MB, kể cả khi chạy test hay chạy trên Kaggle.

Mỗi chỉ số có hai hệ số:
- `or_marginal`: odds ratio khi xét riêng chỉ số đó (hồi quy logistic một biến).
- `or_adjusted`: odds ratio trong mô hình logistic có đủ 21 chỉ số, tức đã trừ phần chồng lấn với các chỉ số khác.
Chỉ số nhị phân tính cho "có so với không"; chỉ số còn lại tính cho mỗi độ lệch chuẩn.
Đây là MỐI LIÊN HỆ trong dữ liệu khảo sát cắt ngang, không phải quan hệ nhân quả.

Chạy:  python tools/build_kg_stats.py [đường_dẫn_csv]
Mặc định đọc ../diacare_datasets/brfss/cdc_diabetes_health_indicators.csv hoặc biến DIACARE_BRFSS.
Script không tự tải dữ liệu.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from diacare.rules import BINARY_FEATURES, FEATURE_RANGES  # noqa: E402

DEFAULT_CSV = ROOT.parent / "diacare_datasets" / "brfss" / "cdc_diabetes_health_indicators.csv"
OUT = ROOT / "kb" / "graph" / "brfss_associations.json"
LABEL = "Diabetes_binary"


def _design(df, cols):
    """Chuẩn hoá chỉ số không nhị phân về độ lệch chuẩn, giữ nguyên chỉ số 0/1."""
    x = df[cols].astype(float).copy()
    for c in cols:
        if c not in BINARY_FEATURES:
            x[c] = (x[c] - x[c].mean()) / x[c].std()
    return x.to_numpy()


def _fit(x, y):
    # C rất lớn tức gần như không phạt: cần hệ số thật, không cần mô hình dự đoán tốt.
    return LogisticRegression(C=1e6, max_iter=2000).fit(x, y)


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DIACARE_BRFSS", DEFAULT_CSV))
    if not path.exists():
        raise SystemExit(f"Không thấy {path}. Tải CDC Diabetes Health Indicators (UCI id 891) rồi chỉ đường dẫn.")
    df = pd.read_csv(path)
    feats = list(FEATURE_RANGES)
    y = df[LABEL].astype(int).to_numpy()

    adjusted = _fit(_design(df, feats), y).coef_[0]
    out = {}
    for i, f in enumerate(feats):
        marginal = _fit(_design(df, [f]), y).coef_[0][0]
        row = {
            "binary": f in BINARY_FEATURES,
            "unit": "có so với không" if f in BINARY_FEATURES else "mỗi độ lệch chuẩn",
            "or_marginal": round(float(np.exp(marginal)), 3),
            "or_adjusted": round(float(np.exp(adjusted[i])), 3),
        }
        if f in BINARY_FEATURES:
            row["prevalence_with"] = round(float(y[df[f] == 1].mean()), 4)
            row["prevalence_without"] = round(float(y[df[f] == 0].mean()), 4)
        out[f] = row

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "CDC Diabetes Health Indicators (BRFSS 2015), UCI id 891",
        "n": int(len(df)),
        "positive_rate": round(float(y.mean()), 4),
        "note": "Mối liên hệ trong dữ liệu khảo sát cắt ngang, không phải quan hệ nhân quả.",
        "features": out,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Đã ghi {OUT} ({len(out)} chỉ số, n = {len(df):,})")


if __name__ == "__main__":
    main()
