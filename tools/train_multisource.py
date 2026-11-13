"""Huấn luyện Predictor trên nhiều nguồn và so với mô hình cũ (chỉ BRFSS 2015) trên cùng các tập kiểm tra.

Đầu vào: data/multisource/*.parquet (tools/build_multisource.py).
Mỗi nguồn chia phân tầng 70% huấn luyện / 10% hiệu chỉnh / 20% kiểm tra (hạt giống 42). Bộ chuẩn hoá,
giá trị điền thiếu và bộ hiệu chỉnh chỉ học trên phần huấn luyện / hiệu chỉnh, không chạm tập kiểm tra.

So sánh:
- old_mlp: Predictor cũ (MLP, BRFSS 2015, pos_weight); chỉ số thiếu điền bằng trung vị BRFSS 2015. Mô hình này
  học trên một cách chia 80/20 khác nên có thể đã thấy một phần tập kiểm tra BRFSS 2015: AUC của nó trên
  BRFSS 2015 là con số lạc quan; BRFSS 2023 và NHANES mới là tập ngoài thật sự với nó.
- lr_pooled: hồi quy logistic trên 3 nguồn (mốc tuyến tính).
- mlp_pooled: MLP 21 chỉ số + 21 cờ "thiếu", 3 nguồn, BCE thường.
- hgb_pooled: HistGradientBoosting (tự xử lý NaN), 3 nguồn.
Mô hình tốt nhất được hiệu chỉnh isotonic trên phần hiệu chỉnh gộp và lưu thành models/predictor_ms.joblib.

Đánh giá trên tập kiểm tra từng nguồn: AUC, Brier, ECE (10 ô). Riêng NHANES thêm:
- nhãn xét nghiệm (tự khai hoặc HbA1c >= 6,5% hoặc đường huyết đói >= 126): mô hình lối sống có bắt được
  ĐTĐ được xác nhận bằng xét nghiệm không;
- người chưa từng được chẩn đoán: AUC phát hiện ĐTĐ chưa chẩn đoán (dương theo xét nghiệm, tự khai không).
Thêm thí nghiệm bỏ-một-nguồn (leave-one-source-out) với HGB.

Chạy:  python tools/train_multisource.py
"""
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from torch import nn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from diacare.model import MLP  # noqa: E402
from diacare.predictor import Predictor  # noqa: E402

DATA = ROOT / "data" / "multisource"
MODELS = ROOT / "models"
RESULT = ROOT / "docs" / "results" / "multisource_eval.json"
SOURCES = ("brfss2015", "brfss2023", "nhanes")
FEATURES = ["HighBP", "HighChol", "CholCheck", "BMI", "Smoker", "Stroke", "HeartDiseaseorAttack", "PhysActivity",
            "Fruits", "Veggies", "HvyAlcoholConsump", "AnyHealthcare", "NoDocbcCost", "GenHlth", "MentHlth",
            "PhysHlth", "DiffWalk", "Sex", "Age", "Education", "Income"]
LABEL = "Diabetes_binary"
SEED = 42


def split(df):
    tr, rest = train_test_split(df, test_size=0.3, stratify=df[LABEL], random_state=SEED)
    cal, te = train_test_split(rest, test_size=2 / 3, stratify=rest[LABEL], random_state=SEED)
    return tr, cal, te


def ece(y, p, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    return float(sum(abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).mean()
                     for b in range(bins) if (idx == b).any()))


def metrics(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    return {"n": int(len(y)), "pos": round(float(y.mean()), 4), "auc": round(float(roc_auc_score(y, p)), 4),
            "brier": round(float(brier_score_loss(y, p)), 4), "ece": round(ece(y, p), 4)}


# ---------- mô hình ----------

class Imputer:
    """Điền trung vị (học trên tập huấn luyện) + cờ thiếu cho từng chỉ số."""

    def __init__(self, df):
        self.med = df[FEATURES].median()
        self.mu, self.sd = None, None

    def transform(self, df, flags=True):
        x = df[FEATURES]
        miss = x.isna().to_numpy(np.float32)
        filled = x.fillna(self.med).to_numpy(np.float32)
        return np.hstack([filled, miss]) if flags else filled


class TorchMLP:
    def __init__(self, d, epochs=12, seed=SEED):
        torch.manual_seed(seed)
        self.net, self.epochs = MLP(d), epochs

    def fit(self, X, y):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-6
        Xt = torch.from_numpy(((X - self.mu) / self.sd).astype(np.float32))
        yt = torch.from_numpy(y.astype(np.float32))
        opt = torch.optim.Adam(self.net.parameters(), lr=1e-3)
        loss_fn = nn.BCEWithLogitsLoss()
        for _ in range(self.epochs):
            self.net.train()
            perm = torch.randperm(len(Xt))
            for i in range(0, len(Xt), 1024):
                idx = perm[i:i + 1024]
                opt.zero_grad()
                loss_fn(self.net(Xt[idx]), yt[idx]).backward()
                opt.step()
        self.net.eval()
        return self

    def predict_proba(self, X):
        with torch.no_grad():
            z = torch.from_numpy(((X - self.mu) / self.sd).astype(np.float32))
            return torch.sigmoid(self.net(z)).numpy()


def old_predictor_proba(old, med15, df):
    x = df[FEATURES].fillna(med15).to_numpy(np.float32)
    x = old.scaler.transform(x).astype(np.float32)
    with torch.no_grad():
        return torch.sigmoid(old.model(torch.from_numpy(x))).numpy()


def evaluate(proba_fn, tests):
    out = {}
    for name, te in tests.items():
        p = proba_fn(te)
        out[name] = metrics(te[LABEL], p)
        if name == "nhanes":
            lab = te["diabetes_lab"].notna()
            out["nhanes_lab_label"] = metrics(te.loc[lab, "diabetes_lab"], p[lab.to_numpy()])
            und = lab & (te[LABEL] == 0)
            out["nhanes_undiagnosed"] = metrics(te.loc[und, "diabetes_lab"], p[und.to_numpy()])
    return out


def main():
    t0 = time.time()
    frames = {s: pd.read_parquet(DATA / f"{s}.parquet") for s in SOURCES}
    parts = {s: split(df) for s, df in frames.items()}
    train = pd.concat([parts[s][0] for s in SOURCES], ignore_index=True)
    calib = pd.concat([parts[s][1] for s in SOURCES], ignore_index=True)
    tests = {s: parts[s][2] for s in SOURCES}
    imp = Imputer(train)
    Xtr, ytr = imp.transform(train), train[LABEL].to_numpy()
    res = {"split": "mỗi nguồn 70/10/20 phân tầng, hạt giống 42",
           "train_rows": {s: int(len(parts[s][0])) for s in SOURCES}, "models": {}}

    old = Predictor(MODELS, kind="v1")
    med15 = parts["brfss2015"][0][FEATURES].median()
    res["models"]["old_mlp"] = evaluate(lambda d: old_predictor_proba(old, med15, d), tests)
    print("old_mlp", {k: v["auc"] for k, v in res["models"]["old_mlp"].items()})

    lr = LogisticRegression(max_iter=2000).fit((Xtr - Xtr.mean(0)) / (Xtr.std(0) + 1e-6), ytr)
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
    res["models"]["lr_pooled"] = evaluate(lambda d: lr.predict_proba((imp.transform(d) - mu) / sd)[:, 1], tests)
    print("lr_pooled", {k: v["auc"] for k, v in res["models"]["lr_pooled"].items()})

    mlp = TorchMLP(Xtr.shape[1]).fit(Xtr, ytr)
    res["models"]["mlp_pooled"] = evaluate(lambda d: mlp.predict_proba(imp.transform(d)), tests)
    print("mlp_pooled", {k: v["auc"] for k, v in res["models"]["mlp_pooled"].items()})

    hgb = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.06, max_leaf_nodes=48,
                                         early_stopping=True, random_state=SEED)
    hgb.fit(train[FEATURES].to_numpy(np.float32), ytr)
    res["models"]["hgb_pooled"] = evaluate(lambda d: hgb.predict_proba(d[FEATURES].to_numpy(np.float32))[:, 1],
                                           tests)
    print("hgb_pooled", {k: v["auc"] for k, v in res["models"]["hgb_pooled"].items()})

    # chọn mô hình theo AUC trung bình trên ba nguồn, rồi hiệu chỉnh isotonic trên phần hiệu chỉnh gộp
    best = max(("mlp_pooled", "hgb_pooled"),
               key=lambda m: np.mean([res["models"][m][s]["auc"] for s in SOURCES]))
    raw = {"mlp_pooled": lambda d: mlp.predict_proba(imp.transform(d)),
           "hgb_pooled": lambda d: hgb.predict_proba(d[FEATURES].to_numpy(np.float32))[:, 1]}[best]
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw(calib), calib[LABEL])
    res["models"][best + "_calibrated"] = evaluate(lambda d: iso.predict(raw(d)), tests)
    res["chosen"] = best + "_calibrated"
    print(res["chosen"], {k: (v["auc"], v["brier"], v["ece"]) for k, v in res["models"][res["chosen"]].items()})

    # bỏ-một-nguồn: huấn luyện HGB trên hai nguồn, kiểm tra trên nguồn thứ ba
    res["leave_one_source_out"] = {}
    for held in SOURCES:
        tr = pd.concat([parts[s][0] for s in SOURCES if s != held], ignore_index=True)
        m = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.06, max_leaf_nodes=48,
                                           early_stopping=True, random_state=SEED)
        m.fit(tr[FEATURES].to_numpy(np.float32), tr[LABEL].to_numpy())
        p = m.predict_proba(tests[held][FEATURES].to_numpy(np.float32))[:, 1]
        res["leave_one_source_out"][held] = metrics(tests[held][LABEL], p)
    print("LOSO", {k: v["auc"] for k, v in res["leave_one_source_out"].items()})

    # phân bố xác suất đã hiệu chỉnh trên BRFSS 2015 kiểm tra, để chọn ngưỡng mức nguy cơ
    p15 = iso.predict(raw(tests["brfss2015"]))
    res["calibrated_quantiles_brfss2015"] = {q: round(float(np.quantile(p15, q)), 4)
                                            for q in (0.25, 0.5, 0.75, 0.9, 0.95)}
    bundle = {"kind": best, "features": FEATURES, "imputer_median": imp.med.to_dict(), "calibrator": iso,
              "trained_on": {s: int(len(parts[s][0])) for s in SOURCES}}
    if best == "hgb_pooled":
        bundle["model"] = hgb
    else:
        bundle.update(model_state=mlp.net.state_dict(), mu=mlp.mu, sd=mlp.sd)
    joblib.dump(bundle, MODELS / "predictor_ms.joblib")
    res["seconds"] = round(time.time() - t0, 1)
    RESULT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("đã lưu", MODELS / "predictor_ms.joblib", "và", RESULT, f"({res['seconds']} s)")


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    main()
