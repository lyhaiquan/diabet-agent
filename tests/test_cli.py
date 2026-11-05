import json

import pytest

import cli
from diacare.factory import open_store
from diacare.samples import HIGH_RISK


@pytest.fixture
def env(tmp_path, monkeypatch):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "ada.txt").write_text("Ăn nhiều rau xanh và hạn chế đường.", encoding="utf-8")
    monkeypatch.setenv("DIACARE_LLM", "demo")
    monkeypatch.setenv("DIACARE_EMBED", "hash")
    monkeypatch.setenv("DIACARE_KB", str(kb))
    monkeypatch.setenv("DIACARE_DB", str(tmp_path / "t.db"))
    return tmp_path


def run_cli(argv, lines):
    it = iter(lines)

    def input_fn(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    out = []
    code = cli.main(argv, input_fn=input_fn, print_fn=lambda *a: out.append(" ".join(map(str, a))))
    return code, "\n".join(out)


def test_question_round_trip(env):
    code, out = run_cli([], ["", "Nên ăn rau không?"])
    assert code == 0
    assert "Theo tài liệu [ada.txt]" in out and "nguy cơ" in out and "Token:" in out
    store = open_store()
    assert len(store.runs()) == 1
    sid = store.runs()[0]["session_id"]
    assert [m["role"] for m in store.get_history(sid)] == ["user", "assistant"]
    assert store.list_patients()[0]["name"] == "Mẫu"


def test_profile_import(env):
    f = env / "p.json"
    f.write_text(json.dumps(HIGH_RISK), encoding="utf-8")
    code, out = run_cli(["--profile", str(f), "--name", "Lan"], ["q"])
    assert code == 0
    ps = open_store().list_patients()
    assert ps[0]["name"] == "Lan" and ps[0]["profile"] == HIGH_RISK


def test_invalid_profile_rejected(env):
    f = env / "bad.json"
    f.write_text(json.dumps({"BMI": 22}), encoding="utf-8")
    code, out = run_cli(["--profile", str(f)], ["hello"])
    assert code == 1 and "Hồ sơ không hợp lệ" in out
    assert open_store().list_patients() == []


def test_patients_and_stats_commands(env):
    code, out = run_cli([], ["/patients", "/stats", "/history", "/q"])
    assert code == 0
    assert "Mẫu" in out and "runs: 0" in out and "chưa có tin nhắn" in out


def test_unknown_patient(env):
    code, out = run_cli(["--patient", "99"], [])
    assert code == 1 and "99" in out


def test_eof_exits_cleanly(env):
    code, _ = run_cli([], [])
    assert code == 0
