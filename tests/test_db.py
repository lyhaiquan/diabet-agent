from diacare.db import Store
from diacare.samples import LOW_RISK
from diacare.state import State


def make_state(question="Ăn gì?", risk=0.4, flags=None, usage=None, docs=None):
    return State(
        question=question,
        profile=LOW_RISK,
        risk=risk,
        docs=docs if docs is not None else [{"source": "ada.txt", "text": "x"}],
        draft="nháp",
        final="kết quả",
        flags=flags or [],
        usage=usage or {},
    )


def test_patient_round_trip():
    s = Store()
    pid = s.save_patient("Nguyễn Văn Ạ", LOW_RISK)
    p = s.get_patient(pid)
    assert p["id"] == pid and p["name"] == "Nguyễn Văn Ạ"
    assert p["profile"] == LOW_RISK
    assert p["created_at"]


def test_list_patients_newest_first():
    s = Store()
    a = s.save_patient("A", LOW_RISK)
    b = s.save_patient("B", LOW_RISK)
    assert [p["id"] for p in s.list_patients()] == [b, a]


def test_get_missing_patient_is_none():
    assert Store().get_patient(999) is None


def test_messages_chronological_and_limit_keeps_newest():
    s = Store()
    sid = s.start_session()
    for i in range(5):
        s.add_message(sid, "user" if i % 2 == 0 else "assistant", f"m{i}")
    assert [m["content"] for m in s.get_history(sid)] == ["m0", "m1", "m2", "m3", "m4"]
    assert s.get_history(sid, limit=2) == [
        {"role": "assistant", "content": "m3"},
        {"role": "user", "content": "m4"},
    ]


def test_log_run_round_trip_with_none_session():
    s = Store()
    state = make_state(flags=["high_risk_referral"], usage={"prompt_tokens": 5})
    rid = s.log_run(None, state)
    assert isinstance(rid, int)
    (r,) = s.runs()
    assert r["session_id"] is None
    assert r["question"] == "Ăn gì?" and r["risk"] == 0.4
    assert r["flags"] == ["high_risk_referral"] and r["sources"] == ["ada.txt"]
    assert r["usage"] == {"prompt_tokens": 5}
    assert r["draft"] == "nháp" and r["final"] == "kết quả" and r["error"] is None


def test_log_run_with_session_and_error():
    s = Store()
    sid = s.start_session()
    s.log_run(sid, make_state(), error="RuntimeError")
    assert s.runs()[0]["session_id"] == sid and s.runs()[0]["error"] == "RuntimeError"


def test_runs_newest_first_and_limit():
    s = Store()
    s.log_run(None, make_state("q1"))
    s.log_run(None, make_state("q2"))
    assert [r["question"] for r in s.runs()] == ["q2", "q1"]
    assert len(s.runs(limit=1)) == 1


def test_run_stats_empty():
    st = Store().run_stats()
    assert st["runs"] == 0 and st["errors"] == 0
    assert st["avg_prompt_tokens"] is None
    assert st["avg_completion_tokens"] is None
    assert st["avg_seconds"] is None
    assert st["flag_counts"] == {}


def test_run_stats_two_runs():
    s = Store()
    s.log_run(None, make_state(flags=["a", "b"], usage={"prompt_tokens": 100, "completion_tokens": 20, "seconds": 2.0}))
    s.log_run(None, make_state(flags=["a"], usage={"prompt_tokens": 300, "completion_tokens": 40, "seconds": 4.0}), error="X")
    s.log_run(None, make_state(flags=["system_error"]))  # empty usage ignored for averages
    st = s.run_stats()
    assert st["runs"] == 3 and st["errors"] == 1
    assert st["avg_prompt_tokens"] == 200.0
    assert st["avg_completion_tokens"] == 30.0
    assert st["avg_seconds"] == 3.0
    assert st["flag_counts"] == {"a": 2, "b": 1, "system_error": 1}


def test_file_store_persists(tmp_path):
    path = tmp_path / "d.db"
    s = Store(path)
    pid = s.save_patient("B", LOW_RISK)
    s.log_run(None, make_state())
    s.close()
    s2 = Store(path)
    assert s2.get_patient(pid)["name"] == "B"
    assert len(s2.runs()) == 1
    s2.close()


def test_old_db_without_trace_column_is_migrated(tmp_path):
    import sqlite3
    from diacare.db import Store
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, ts TEXT NOT NULL,"
                " question TEXT, risk REAL, flags_json TEXT, sources_json TEXT, draft TEXT, final TEXT,"
                " usage_json TEXT, error TEXT)")
    con.execute("INSERT INTO runs (ts, question) VALUES ('2026-01-01', 'cũ')")
    con.commit()
    con.close()
    store = Store(path)
    assert store.runs()[0]["trace"] == []
