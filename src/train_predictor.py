"""V1 Predictor: du doan nguy co tieu duong tren CDC BRFSS 2015 (UCI id 891).

Chay: python src/train_predictor.py
Ket qua: models/predictor.pt, models/scaler.joblib, in AUC/F1/recall cua baseline va MLP.
"""
from pathlib import Path

import joblib
import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from torch import nn
from ucimlrepo import fetch_ucirepo

from diacare.model import MLP

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
MODELS.mkdir(exist_ok=True)
torch.manual_seed(42)
np.random.seed(42)


def load_data():
    ds = fetch_ucirepo(id=891)  # CDC Diabetes Health Indicators
    X = ds.data.features
    y = ds.data.targets.iloc[:, 0].values.astype("float32")
    return X, y


def report(name, y_true, prob):
    pred = (prob >= 0.5).astype(int)
    print(f"{name:>18} | AUC {roc_auc_score(y_true, prob):.3f} "
          f"| F1 {f1_score(y_true, pred):.3f} | Recall {recall_score(y_true, pred):.3f}")


def main():
    X, y = load_data()
    print("Du lieu:", X.shape, "ti le benh:", y.mean().round(3))
    Xtr, Xte, ytr, yte = train_test_split(X.values, y, test_size=0.2, stratify=y, random_state=42)
    scaler = StandardScaler().fit(Xtr)
    Xtr, Xte = scaler.transform(Xtr).astype("float32"), scaler.transform(Xte).astype("float32")

    # Baseline
    lr = LogisticRegression(max_iter=1000, class_weight="balanced").fit(Xtr, ytr)
    report("LogisticRegression", yte, lr.predict_proba(Xte)[:, 1])

    # MLP (class weight de xu ly mat can bang lop)
    model = MLP(Xtr.shape[1])
    pos_w = torch.tensor((1 - ytr.mean()) / ytr.mean())
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_w)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    Xt, yt = torch.from_numpy(Xtr), torch.from_numpy(ytr)
    for epoch in range(15):
        model.train()
        perm = torch.randperm(len(Xt))
        for i in range(0, len(Xt), 512):
            idx = perm[i:i + 512]
            opt.zero_grad()
            loss_fn(model(Xt[idx]), yt[idx]).backward()
            opt.step()
    model.eval()
    with torch.no_grad():
        prob = torch.sigmoid(model(torch.from_numpy(Xte))).numpy()
    report("MLP", yte, prob)

    torch.save({"state": model.state_dict(), "features": list(X.columns)}, MODELS / "predictor.pt")
    joblib.dump(scaler, MODELS / "scaler.joblib")
    print("Da luu model vao", MODELS)


if __name__ == "__main__":
    main()
