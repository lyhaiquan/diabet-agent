from pathlib import Path

import joblib
import numpy as np
import torch

from diacare.model import MLP


class Predictor:
    def __init__(self, model_dir):
        model_dir = Path(model_dir)
        ckpt = torch.load(model_dir / "predictor.pt", map_location="cpu")
        self.features = ckpt["features"]
        self.model = MLP(len(self.features))
        self.model.load_state_dict(ckpt["state"])
        self.model.eval()
        self.scaler = joblib.load(model_dir / "scaler.joblib")

    def predict(self, profile):
        missing = [f for f in self.features if f not in profile]
        if missing:
            raise ValueError(f"missing features: {missing}")
        x = np.array([[profile[f] for f in self.features]], dtype="float32")
        x = self.scaler.transform(x).astype("float32")
        with torch.no_grad():
            return float(torch.sigmoid(self.model(torch.from_numpy(x))).item())
