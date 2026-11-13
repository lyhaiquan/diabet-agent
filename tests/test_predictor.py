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


def test_multisource_predictor_is_default_and_calibrated(predictor):
    from diacare.rules import risk_band
    assert predictor.kind == "multisource"
    assert risk_band(predictor.predict(HIGH_RISK)) == "cao"
    assert risk_band(predictor.predict(LOW_RISK)) == "thấp"
    assert set(predictor.trained_on) == {"brfss2015", "brfss2023", "nhanes"}


def test_v1_predictor_still_available():
    old = Predictor(MODELS, kind="v1")
    assert old.predict(HIGH_RISK) > old.predict(LOW_RISK)
    with pytest.raises(ValueError):
        Predictor(MODELS, kind="khac")


def test_bench_report_renders_multisource_metrics():
    import json
    from diacare.bench import build_report
    pm = json.loads((MODELS / "metrics.json").read_text(encoding="utf-8"))
    rep = build_report({}, {"title": "t", "predictor_metrics": pm, "k": 1, "n_cases": 0})
    assert "| nhanes |" in rep and "AUC mô hình cũ" in rep
