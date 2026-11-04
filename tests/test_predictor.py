from pathlib import Path

import pytest
from diacare.predictor import Predictor
from diacare.samples import HIGH_RISK, LOW_RISK

MODELS = Path(__file__).resolve().parent.parent / "models"


@pytest.fixture(scope="module")
def predictor():
    return Predictor(MODELS)


def test_high_risk_scores_above_low_risk(predictor):
    low, high = predictor.predict(LOW_RISK), predictor.predict(HIGH_RISK)
    assert 0.0 <= low <= 1.0 and 0.0 <= high <= 1.0
    assert high > low


def test_missing_feature_raises(predictor):
    bad = dict(LOW_RISK)
    del bad["BMI"]
    with pytest.raises(ValueError, match="BMI"):
        predictor.predict(bad)
