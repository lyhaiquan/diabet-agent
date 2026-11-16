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


# Ngưỡng mức nguy cơ của bản V1 (xác suất MLP chưa hiệu chỉnh); bản đa nguồn dùng 0,10 / 0,30 trong rules.py.
V1_BANDS = (0.20, 0.50)
_COMPARE_CACHE = {}


def _v1_band(p):
    return "thấp" if p < V1_BANDS[0] else ("trung bình" if p < V1_BANDS[1] else "cao")


def compare_models(model_dir, profile):
    """Chạy cùng một hồ sơ qua cả hai mô hình: MLP (học sâu, V1) và boosting đa nguồn đã hiệu chỉnh.

    Dùng để trình diễn và giải thích vì sao bản mặc định không phải MLP: hai mô hình xếp hạng gần như nhau (AUC),
    nhưng xác suất MLP bị đẩy cao do pos_weight nên phải dùng ngưỡng khác. Thiếu tệp mô hình nào thì bỏ mô hình đó.
    """
    from diacare.rules import risk_band

    model_dir = Path(model_dir)
    out = []
    specs = (
        ("v1", "predictor.pt", "MLP 21-64-32-1 (PyTorch, học sâu)", "BRFSS 2015", False, _v1_band),
        ("multisource", "predictor_ms.joblib", "HistGradientBoosting + hiệu chỉnh isotonic",
         "BRFSS 2015, BRFSS 2023, NHANES 2013-2020", True, risk_band),
    )
    for kind, fname, name, data, calibrated, band in specs:
        if not (model_dir / fname).exists():
            continue
        key = (str(model_dir), kind)
        if key not in _COMPARE_CACHE:
            _COMPARE_CACHE[key] = Predictor(model_dir, kind=kind)
        p = _COMPARE_CACHE[key].predict(profile)
        out.append({"kind": kind, "name": name, "trained_on": data, "calibrated": calibrated,
                    "probability": round(float(p), 4), "band": band(p)})
    return out
