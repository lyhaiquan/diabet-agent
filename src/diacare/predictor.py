"""Dự đoán nguy cơ tiểu đường từ 21 chỉ số hồ sơ BRFSS.

Hai phiên bản, cùng giao diện `predict(profile) -> xác suất`:
- "multisource" (mặc định khi có models/predictor_ms.joblib): HistGradientBoosting học trên BRFSS 2015,
  BRFSS 2023 và NHANES 2013-2020, đã hiệu chỉnh isotonic nên xác suất gần với tỉ lệ thật
  (tools/build_multisource.py, tools/train_multisource.py).
- "v1": MLP chỉ học trên BRFSS 2015 (src/train_predictor.py), xác suất chưa hiệu chỉnh. Giữ lại để so sánh;
  chọn bằng DIACARE_PREDICTOR=v1.
"""
import os
from pathlib import Path

import joblib
import numpy as np
import torch

from diacare.model import MLP

PROB_FLOOR, PROB_CEIL = 0.001, 0.999   # isotonic có thể trả 0 tuyệt đối; giữ trong (0, 1) cho dễ đọc


class Predictor:
    def __init__(self, model_dir, kind=None):
        model_dir = Path(model_dir)
        bundle_path = model_dir / "predictor_ms.joblib"
        kind = (kind or os.environ.get("DIACARE_PREDICTOR") or ("multisource" if bundle_path.exists() else "v1"))
        self.kind = kind.lower()
        if self.kind == "multisource":
            bundle = joblib.load(bundle_path)
            self.features = list(bundle["features"])
            self.model, self.calibrator = bundle["model"], bundle["calibrator"]
            self.trained_on = bundle.get("trained_on", {})
        elif self.kind == "v1":
            ckpt = torch.load(model_dir / "predictor.pt", map_location="cpu")
            self.features = ckpt["features"]
            self.model = MLP(len(self.features))
            self.model.load_state_dict(ckpt["state"])
            self.model.eval()
            self.scaler = joblib.load(model_dir / "scaler.joblib")
        else:
            raise ValueError(f"DIACARE_PREDICTOR không biết: {kind!r} (multisource hoặc v1)")

    def predict_many(self, rows):
        """rows: DataFrame có đủ 21 cột. Trả về mảng xác suất (dùng khi tính trên cả bộ dữ liệu)."""
        x = rows[self.features].to_numpy(dtype="float32")
        if self.kind == "multisource":
            return np.clip(self.calibrator.predict(self.model.predict_proba(x)[:, 1]), PROB_FLOOR, PROB_CEIL)
        x = self.scaler.transform(x).astype("float32")
        with torch.no_grad():
            return torch.sigmoid(self.model(torch.from_numpy(x))).numpy().ravel()

    def predict(self, profile):
        missing = [f for f in self.features if f not in profile]
        if missing:
            raise ValueError(f"missing features: {missing}")
        x = np.array([[profile[f] for f in self.features]], dtype="float32")
        if self.kind == "multisource":
            p = self.calibrator.predict(self.model.predict_proba(x)[:, 1])[0]
            return float(np.clip(p, PROB_FLOOR, PROB_CEIL))
        x = self.scaler.transform(x).astype("float32")
        with torch.no_grad():
            return float(torch.sigmoid(self.model(torch.from_numpy(x))).item())
