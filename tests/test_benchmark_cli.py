import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
import benchmark  # noqa: E402


def make_kb(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "ada.txt").write_text(
        "Người bị tiền đái tháo đường nên ăn nhiều rau, hạn chế đường và tập thể dục đều đặn.",
        encoding="utf-8")
    return kb


def test_cli_demo_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv("DIACARE_LLM", raising=False)
    kb = make_kb(tmp_path)
    out = tmp_path / "out"
    rc = benchmark.main(["--llm", "demo", "--embed", "hash", "--kb", str(kb), "--k", "2",
                         "--out", str(out), "--predictor-metrics", str(tmp_path / "none.json")])
    assert rc == 0
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "BẢN DEMO — số liệu không phản ánh mô hình thật" in report
    assert "Pass^2" in report
    data = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert data["meta"]["k"] == 2 and "demo" in data["results"]
    assert len(data["results"]["demo"]["runs"]) == 46
    assert list(out.glob("*.png"))


def test_cli_loads_predictor_metrics(tmp_path):
    kb = make_kb(tmp_path)
    pm = tmp_path / "m.json"
    pm.write_text(json.dumps({"source": "s", "n_samples": 5, "split": "80/20",
                              "models": {"MLP": {"auc": 0.9, "f1": 0.5, "recall": 0.7}}}), encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([{"id": "a", "category": "diet", "profile": "low", "q": "Ăn gì?"}]),
                     encoding="utf-8")
    out = tmp_path / "out"
    benchmark.main(["--llm", "demo", "--embed", "hash", "--kb", str(kb), "--k", "1", "--out", str(out),
                    "--cases", str(cases), "--predictor-metrics", str(pm)])
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "0.900" in report and "MLP" in report


class DeadLLM:
    num_ctx = 4096
    last_usage = {}

    def __call__(self, messages):
        raise ConnectionError("ollama down")


def test_cli_warns_when_ollama_unreachable(tmp_path, monkeypatch):
    kb = make_kb(tmp_path)
    monkeypatch.setattr(benchmark, "make_llm", lambda kind, model=None, num_ctx=None: DeadLLM())
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([{"id": "a", "category": "diet", "profile": "low", "q": "Ăn gì?"}]),
                     encoding="utf-8")
    out = tmp_path / "out"
    rc = benchmark.main(["--llm", "ollama", "--embed", "hash", "--kb", str(kb), "--k", "2",
                         "--out", str(out), "--cases", str(cases), "--models", "foo:1b",
                         "--predictor-metrics", str(tmp_path / "none.json")])
    assert rc == 0
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "Ollama không phản hồi: kiểm tra `ollama serve` và tên model" in report
    assert report.index("Ollama không phản hồi") < report.index("Cấu hình đo")
    assert "BẢN DEMO" not in report


def test_cli_features_recorded_in_meta_and_report(tmp_path):
    kb = make_kb(tmp_path)
    out = tmp_path / "out"
    rc = benchmark.main(["--llm", "demo", "--embed", "hash", "--kb", str(kb), "--k", "1", "--features", "v1",
                         "--out", str(out), "--predictor-metrics", str(tmp_path / "none.json")])
    assert rc == 0
    assert json.loads((out / "results.json").read_text(encoding="utf-8"))["meta"]["features"] == []
    assert "Tính năng V2: không (V1)" in (out / "report.md").read_text(encoding="utf-8")
