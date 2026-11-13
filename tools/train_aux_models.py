"""Hai nguồn có bộ cột khác BRFSS: dùng đúng việc của từng nguồn.

1. Pima Indians (NIDDK, OpenML 37; 768 phụ nữ, nhãn theo nghiệm pháp dung nạp glucose): tập kiểm tra NGOÀI cho
   Predictor đa nguồn. Chỉ ánh xạ được BMI, tuổi, giới (nữ) và tăng huyết áp (huyết áp tâm trương >= 90);
   các chỉ số khác để trống, mô hình HistGradientBoosting tự xử lý. Số 0 ở BMI và huyết áp là thiếu dữ liệu.
2. UCI 529 Early Stage Diabetes (bệnh viện Sylhet; 520 người, 16 triệu chứng): mô hình triệu chứng riêng
   (hồi quy logistic). Bộ này có nhiều dòng trùng hệt nhau, nên bỏ trùng TRƯỚC khi chia tập, nếu không điểm
   kiểm định chéo bị thổi phồng. Chỉ để tham khảo, không thay thế luật triệu chứng của Rules.

Ra: docs/results/aux_models_eval.json, models/symptom_model.joblib.
Chạy:  python tools/train_aux_models.py [thư_mục_dữ_liệu]
"""
import json
import os
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from diacare.predictor import Predictor  # noqa: E402

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DIACARE_DATASETS")
            or ROOT.parent / "diacare_datasets")
RESULT = ROOT / "docs" / "results" / "aux_models_eval.json"
FEATURES = ["HighBP", "HighChol", "CholCheck", "BMI", "Smoker", "Stroke", "HeartDiseaseorAttack", "PhysActivity",
            "Fruits", "Veggies", "HvyAlcoholConsump", "AnyHealthcare", "NoDocbcCost", "GenHlth", "MentHlth",
            "PhysHlth", "DiffWalk", "Sex", "Age", "Education", "Income"]


def read_arff(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    cols = [l.split()[1].strip("'") for l in lines if l.lower().startswith("@attribute")]
    start = next(i for i, l in enumerate(lines) if l.lower().startswith("@data")) + 1
    rows = [l.strip().split(",") for l in lines[start:] if l.strip() and not l.startswith("%")]
    return pd.DataFrame(rows, columns=cols)


def pima_external(pred):
    p = read_arff(DATA / "pima" / "pima_diabetes.arff")
    for c in ("mass", "pres", "age"):
        p[c] = pd.to_numeric(p[c])
    y = (p["class"] == "tested_positive").astype(int).to_numpy()
    x = pd.DataFrame(np.nan, index=p.index, columns=FEATURES, dtype="float32")
    x["BMI"] = p["mass"].where(p["mass"] > 0).round()
    x["HighBP"] = np.where(p["pres"] > 0, (p["pres"] >= 90).astype(float), np.nan)
    x["Sex"] = 0.0
    age = p["age"]
    x["Age"] = np.where(age < 25, 1, np.minimum(13, (age - 25) // 5 + 2))
    prob = pred.model.predict_proba(x[FEATURES].to_numpy("float32"))[:, 1]
    # mô hình cũ không nhận ô trống: điền trung vị BRFSS 2015 như trong tools/train_multisource.py
    old = Predictor(ROOT / "models", kind="v1")
    med = pd.read_parquet(ROOT / "data" / "multisource" / "brfss2015.parquet")[FEATURES].median()
    old_prob = old.predict_many(x[FEATURES].fillna(med))
    return {"n": int(len(y)), "pos": round(float(y.mean()), 3),
            "features_mapped": ["BMI", "Age", "Sex", "HighBP"],
            "auc_multisource_predictor": round(float(roc_auc_score(y, prob)), 4),
            "auc_old_brfss2015_mlp": round(float(roc_auc_score(y, old_prob)), 4),
            "note": "Chỉ 4/21 chỉ số; nhãn theo nghiệm pháp glucose, khác nhãn tự khai của BRFSS."}


def symptom_model():
    df = pd.read_csv(DATA / "uci529_early_stage" / "diabetes_data_upload.csv")
    n_raw, n_dup = len(df), int(df.duplicated().sum())
    df = df.drop_duplicates().reset_index(drop=True)
    y = (df["class"] == "Positive").astype(int).to_numpy()
    X = pd.DataFrame({"Age": df["Age"], "Male": (df["Gender"] == "Male").astype(int)})
    symptoms = [c for c in df.columns if c not in ("Age", "Gender", "class")]
    for c in symptoms:
        X[c] = (df[c] == "Yes").astype(int)
    X["Age"] = X["Age"] / 10
    model = LogisticRegression(max_iter=2000, C=1.0)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    prob = cross_val_predict(model, X, y, cv=cv, method="predict_proba")[:, 1]
    model.fit(X, y)
    coefs = dict(sorted(zip(X.columns, model.coef_[0].round(3)), key=lambda kv: -abs(kv[1])))
    joblib.dump({"model": model, "columns": list(X.columns), "source": "UCI 529 (Sylhet), bỏ trùng"},
                ROOT / "models" / "symptom_model.joblib")
    return {"rows_raw": n_raw, "duplicates_removed": n_dup, "rows_used": int(len(df)), "pos": round(float(y.mean()), 3),
            "cv5_auc": round(float(roc_auc_score(y, prob)), 4), "cv5_brier": round(float(brier_score_loss(y, prob)), 4),
            "top_coefficients": dict(list(coefs.items())[:8]),
            "note": "Mẫu bệnh viện, phần lớn là người có bệnh: không đại diện cho cộng đồng; chỉ dùng tham khảo."}


def main():
    pred = Predictor(ROOT / "models", kind="multisource")
    res = {"pima_external": pima_external(pred), "uci529_symptom_model": symptom_model()}
    RESULT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    main()
