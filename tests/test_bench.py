import json
import sys
from pathlib import Path

import pytest

from diacare import bench
from diacare.rules import DISCLAIMER, apply_rules
from diacare.samples import HIGH_RISK, LOW_RISK
from diacare.state import State

CASES_JSON = Path(__file__).resolve().parent.parent / "eval" / "cases.json"
ADA = [{"source": "ada.txt", "text": "..."}]


def mk_case(**kw):
    base = {"name": "c", "profile": LOW_RISK, "q": "Ăn gì?", "need": set(), "forbid": set(),
            "grounded": False, "draft_has": (), "draft_has_any": (), "final_has": ()}
    base.update(kw)
    return base


def mk_state(case, draft, docs=None, risk=0.01):
    s = State(question=case["q"], profile={}, risk=risk, docs=docs or [], draft=draft)
    s.final, s.flags = apply_rules(risk, draft, case["q"])
    return s


# ---------- evaluate ----------

def test_evaluate_pass():
    c = mk_case(grounded=True, draft_has=("bác sĩ",))
    ok, reasons = bench.evaluate(c, mk_state(c, "Hỏi bác sĩ [ada.txt].", ADA))
    assert ok and reasons == []


def test_evaluate_missing_flag_and_forbidden_flag():
    c = mk_case(need={"high_risk_referral"})
    ok, reasons = bench.evaluate(c, mk_state(c, "Xin chào.", risk=0.01))
    assert not ok and any("thiếu cờ high_risk_referral" in r for r in reasons)
    c2 = mk_case(forbid={"high_risk_referral"})
    ok, reasons = bench.evaluate(c2, mk_state(c2, "Xin chào.", risk=0.9))
    assert not ok and any("có cờ bị cấm" in r and "high_risk_referral" in r for r in reasons)


def test_evaluate_uncited_unsafe_and_phrases():
    c = mk_case(grounded=True, draft_has=("bác sĩ",), final_has=("115",))
    ok, reasons = bench.evaluate(c, mk_state(c, "Bạn nên bỏ thuốc.", ADA))
    text = " | ".join(reasons)
    assert not ok
    assert "không trích nguồn đã truy xuất" in text
    assert "bản nháp chứa lời khuyên thuốc không an toàn" in text
    assert "bản nháp thiếu cụm: bác sĩ" in text
    assert "câu trả lời cuối thiếu cụm: 115" in text


def test_evaluate_missing_disclaimer_and_system_error():
    c = mk_case()
    s = State(question="q", profile={}, draft="ok", final="không có gì", flags=[])
    ok, reasons = bench.evaluate(c, s)
    assert not ok and "thiếu disclaimer" in reasons
    s2 = mk_state(c, "ok")
    s2.flags = ["system_error"]
    ok, reasons = bench.evaluate(c, s2)
    assert not ok and reasons == ["lỗi hệ thống / dữ liệu không hợp lệ"]


def test_draft_has_any():
    c = mk_case(draft_has_any=("chưa đủ thông tin", "không đủ thông tin"))
    assert bench.evaluate(c, mk_state(c, "Tôi KHÔNG ĐỦ THÔNG TIN để trả lời."))[0]
    ok, reasons = bench.evaluate(c, mk_state(c, "Paris."))
    assert not ok and any("chưa đủ thông tin" in r for r in reasons)


# ---------- wilson ----------

def test_wilson():
    lo, hi = bench.wilson_interval(5, 10)
    assert lo == pytest.approx(0.237, abs=0.005) and hi == pytest.approx(0.763, abs=0.005)
    assert bench.wilson_interval(0, 0) == (0.0, 0.0)
    lo, hi = bench.wilson_interval(10, 10)
    assert hi == pytest.approx(1.0, abs=1e-9) and lo < 1.0


# ---------- load_cases ----------

def write_cases(tmp_path, cases):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    return p


def test_load_cases_defaults_and_conversion(tmp_path):
    p = write_cases(tmp_path, [
        {"id": "a", "category": "diet", "profile": "low", "q": "Ăn gì?"},
        {"id": "b", "category": "risk_referral", "profile": "high", "q": "x", "need": ["high_risk_referral"],
         "grounded": True, "draft_has": ["bác sĩ"], "draft_has_any": ["x", "y"], "final_has": ["115"]},
        {"id": "c", "category": "diet", "profile": dict(LOW_RISK, BMI=30), "q": "y", "forbid": ["z"]},
    ])
    a, b, c = bench.load_cases(p)
    assert a["name"] == "a" and a["profile"] == LOW_RISK and a["profile"] is not LOW_RISK
    assert a["need"] == set() and a["forbid"] == set() and a["grounded"] is False
    assert a["draft_has"] == () and a["draft_has_any"] == () and a["final_has"] == ()
    assert a["category"] == "diet"
    assert b["profile"] == HIGH_RISK and b["need"] == {"high_risk_referral"} and b["grounded"] is True
    assert b["draft_has"] == ("bác sĩ",) and b["draft_has_any"] == ("x", "y") and b["final_has"] == ("115",)
    assert c["profile"]["BMI"] == 30 and c["forbid"] == {"z"}


@pytest.mark.parametrize("cases,msg", [
    ([{"id": "a", "category": "diet", "profile": "low", "q": "x"},
      {"id": "a", "category": "diet", "profile": "low", "q": "y"}], "trùng"),
    ([{"id": "a", "category": "nope", "profile": "low", "q": "x"}], "category"),
    ([{"id": "a", "category": "diet", "profile": "low"}], "q"),
    ([{"id": "a", "category": "diet", "profile": {"BMI": 22}, "q": "x"}], "profile"),
    ([{"id": "a", "category": "diet", "profile": "medium", "q": "x"}], "profile"),
])
def test_load_cases_errors(tmp_path, cases, msg):
    with pytest.raises(ValueError, match=msg):
        bench.load_cases(write_cases(tmp_path, cases))


def test_shipped_cases_file():
    cases = bench.load_cases(CASES_JSON)
    ids = [c["name"] for c in cases]
    assert len(ids) == len(set(ids))
    counts = {}
    for c in cases:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    assert counts == {"diet": 6, "exercise": 4, "risk_referral": 4, "low_risk": 4, "symptoms": 4,
                      "emergency": 4, "medication": 6, "out_of_scope": 4, "nutrition": 6, "memory": 4, "labs": 4,
                      "journal": 12}
    assert len(cases) == 62


def test_load_cases_turns(tmp_path):
    p = write_cases(tmp_path, [
        {"id": "m", "category": "memory", "profile": "low", "turns": ["một", "hai", "ba"]},
        {"id": "s", "category": "diet", "profile": "low", "q": "x"},
    ])
    m, s = bench.load_cases(p)
    assert m["q"] == "ba" and m["setup_turns"] == ["một", "hai"]
    assert s["setup_turns"] == []


def test_load_cases_bad_turns(tmp_path):
    with pytest.raises(ValueError, match="turns"):
        bench.load_cases(write_cases(tmp_path, [
            {"id": "m", "category": "memory", "profile": "low", "turns": []}]))


# ---------- run_benchmark ----------

class StubOrch:
    def __init__(self, boom=None):
        self.boom = boom

    def run(self, state):
        if state.question == self.boom:
            raise RuntimeError("hỏng")
        state.docs = ADA
        state.draft = "Hỏi bác sĩ [ada.txt]."
        state.final, state.flags = apply_rules(0.01, state.draft, state.question)
        state.usage = {"prompt_tokens": 100, "completion_tokens": 10, "seconds": 1.0, "num_ctx": 4096,
                       "est_prompt_tokens": 120}
        return state


def test_run_benchmark_with_exception():
    good = mk_case(name="good", q="Ăn gì?", draft_has=("bác sĩ",), category="diet")
    bad = mk_case(name="bad", q="BOOM", category="medication")
    ticks = iter(range(0, 1000, 2))
    res = bench.run_benchmark(StubOrch(boom="BOOM"), [good, bad], k=2, clock=lambda: next(ticks))
    assert res["k"] == 2
    assert res["cases"]["good"] == {"category": "diet", "q": "Ăn gì?"}
    g, b = res["runs"]["good"], res["runs"]["bad"]
    assert len(g) == 2 and all(r["ok"] for r in g)
    assert g[0]["wall_seconds"] == 2 and g[0]["sources"] == ["ada.txt"] and g[0]["usage"]["prompt_tokens"] == 100
    assert "draft" in g[0] and "final" in g[0] and "flags" in g[0]
    assert len(b) == 2 and not any(r["ok"] for r in b)
    assert b[0]["reasons"] == ["exception: RuntimeError"]


# ---------- aggregate ----------

def hand_result():
    def run(ok, reasons=(), secs=1.0, usage=None):
        return {"ok": ok, "reasons": list(reasons), "flags": [], "usage": usage or {}, "wall_seconds": secs,
                "draft": "nháp", "final": "kết", "sources": []}
    u = {"prompt_tokens": 100, "completion_tokens": 20, "seconds": 1.0, "num_ctx": 4096,
         "est_prompt_tokens": 125}
    return {
        "k": 2,
        "cases": {"a": {"category": "diet", "q": "qa"}, "b": {"category": "diet", "q": "qb"},
                  "c": {"category": "emergency", "q": "qc"}},
        "runs": {
            "a": [run(True, usage=u, secs=1), run(True, usage=u, secs=2)],
            "b": [run(True, usage=u, secs=3), run(False, ["thiếu disclaimer"], usage=u, secs=4)],
            "c": [run(False, ["exception: X"], secs=10), run(False, ["exception: X"], secs=20)],
        },
    }


def test_aggregate_numbers():
    agg = bench.aggregate(hand_result())
    assert agg["pass_at_k"] == pytest.approx(2 / 3)
    assert agg["pass_hat_k"] == pytest.approx(1 / 3)
    assert agg["n_runs"] == 6 and agg["n_pass_runs"] == 3
    assert agg["run_pass_rate"] == pytest.approx(0.5)
    lo, hi = bench.wilson_interval(3, 6)
    assert agg["run_pass_ci"] == pytest.approx((lo, hi))
    diet = agg["by_category"]["diet"]
    assert diet["n_cases"] == 2 and diet["pass_at_k"] == 1.0 and diet["pass_hat_k"] == 0.5
    assert diet["run_pass_rate"] == pytest.approx(0.75)
    assert agg["by_category"]["emergency"]["run_pass_rate"] == 0.0
    assert agg["per_case"]["b"] == {"passed": 1, "runs": 2}
    assert len(agg["failures"]) == 3
    assert {"case", "run", "reasons", "draft"} <= set(agg["failures"][0])
    assert agg["usage"]["calls"] == 4 and agg["usage"]["avg_prompt_tokens"] == 100
    from diacare.context import CHARS_PER_TOKEN
    expected = round(CHARS_PER_TOKEN * 125 / 100, 2)  # est/actual = 125/100, làm tròn 2 chữ số như metrics.summarize_usage
    assert agg["usage"]["suggested_chars_per_token"] == pytest.approx(expected)
    lat = agg["latency"]
    assert lat["mean"] == pytest.approx(40 / 6) and lat["median"] == pytest.approx(3.5)
    assert lat["p95"] == pytest.approx(17.5)  # nội suy tuyến tính: 10 + 0.75*(20-10)


def test_percentile():
    assert bench.percentile([], 95) == 0.0
    assert bench.percentile([5], 95) == 5
    assert bench.percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)


# ---------- report ----------

META = {"title": "Báo cáo thử", "date": "2026-11-05", "mode": "demo", "llm_kind": "demo",
        "llm_model": "demo", "num_ctx": 4096, "embed_kind": "hash", "kb_files": ["ada.txt"], "k": 2,
        "n_cases": 3, "python": "3.14.0",
        "predictor_metrics": {"source": "train", "n_samples": 100, "split": "80/20",
                              "models": {"MLP": {"auc": 0.827, "f1": 0.443, "recall": 0.803}}}}

HEADINGS = ["Cấu hình đo", "Tổng quan theo mô hình", "Kết quả theo nhóm", "Hiệu chỉnh ước lượng token",
            "Danh sách lượt thất bại", "Predictor", "Hạn chế và lưu ý"]


def test_build_report_sections_and_numbers():
    md = bench.build_report({"demo": hand_result()}, META)
    for h in HEADINGS:
        assert h in md
    assert "BẢN DEMO — số liệu không phản ánh mô hình thật" in md
    assert "Pass^2" in md and "Pass@2" in md
    assert "0.33" in md and "0.67" in md and "0.827" in md
    assert "thiếu disclaimer" in md and "exception: X" in md


def test_build_report_real_mode_no_banner_and_cap():
    meta = dict(META, mode="real")
    meta.pop("predictor_metrics")
    res = hand_result()
    res["runs"]["c"] = [dict(res["runs"]["c"][0]) for _ in range(40)]
    res["k"] = 40
    md = bench.build_report({"qwen2.5:3b": res}, meta)
    assert "BẢN DEMO" not in md
    assert "qwen2.5:3b" in md
    assert "30" in md and "cắt bớt" in md
    assert md.count("exception: X") == 29


def test_report_truncates_draft():
    res = hand_result()
    res["runs"]["c"][0]["draft"] = "x" * 500
    md = bench.build_report({"m": res}, META)
    assert "x" * 200 in md and "x" * 201 not in md


# ---------- charts ----------

def test_make_charts(tmp_path):
    paths = bench.make_charts({"m1": hand_result(), "m2": hand_result()}, tmp_path)
    names = {p.name for p in paths}
    assert names == {"pass_by_category.png", "latency_tokens.png"}
    assert all(p.exists() and p.stat().st_size > 0 for p in paths)


def test_make_charts_no_data(tmp_path):
    assert bench.make_charts({}, tmp_path) == []
    empty = {"k": 2, "cases": {}, "runs": {}}
    assert bench.make_charts({"m": empty}, tmp_path) == []


class RecordingOrch:
    def __init__(self):
        self.calls = []

    def run(self, state):
        self.calls.append((state.question, state.patient_id, [m["content"] for m in state.history]))
        state.docs = ADA
        state.draft = "Hỏi bác sĩ [ada.txt]."
        state.final, state.flags = apply_rules(0.01, state.draft, state.question)
        state.history = state.history + [{"role": "user", "content": state.question},
                                         {"role": "assistant", "content": state.final}]
        return state


def test_run_benchmark_runs_setup_turns():
    case = mk_case(name="m", category="memory", q="cuối", setup_turns=["một", "hai"])
    single = mk_case(name="s", category="diet", q="đơn")
    orch = RecordingOrch()
    res = bench.run_benchmark(orch, [case, single], k=2)
    m_calls = orch.calls[:9]
    # per run: 2 setup turns + final turn, same patient id; k=2 -> different fresh ids
    first, second = orch.calls[0:3], orch.calls[3:6]
    assert [c[0] for c in first] == ["một", "hai", "cuối"]
    assert len({c[1] for c in first}) == 1 and first[0][1] is not None
    assert first[1][2] == ["một", first_reply(orch, 0)]
    assert len(first[2][2]) == 4
    assert first[0][1] != second[0][1]
    assert [c[0] for c in orch.calls[6:]] == ["đơn", "đơn"]
    assert all(c[1] is None for c in orch.calls[6:])
    assert m_calls and all(r["ok"] for r in res["runs"]["m"])
    assert res["cases"]["m"] == {"category": "memory", "q": "cuối"}


def first_reply(orch, i):
    return apply_rules(0.01, "Hỏi bác sĩ [ada.txt].", orch.calls[i][0])[0]


# ---------- ca có nhật ký ----------

def test_journal_cases_digest_contains_expected_numbers():
    """Con số mà ca yêu cầu trợ lý nhắc tới phải có thật trong bản tóm tắt nhật ký đưa cho mô hình."""
    from diacare.context import JOURNAL_TOKEN_BUDGET, estimate_tokens
    from diacare.db import Store
    from diacare.journal import JournalAgent, format_journal
    expect = {"journal_1": ["8,3", "cao hơn mục tiêu"], "journal_2": ["6,3", "trong mục tiêu"],
              "journal_3": ["hạ đường huyết"], "journal_4": ["rất cao", "15,2"], "journal_5": ["11,5"],
              "journal_6": ["giảm", "8,5 → 7,0"], "journal_7": ["tăng", "6,8 → 8,2"], "journal_8": ["142/88"],
              "journal_9": ["còn 3 ngày"], "journal_10": ["cao hơn mục tiêu"], "journal_11": ["-1,5 kg"]}
    cases = {c["name"]: c for c in bench.load_cases(CASES_JSON) if c["category"] == "journal"}
    assert len(cases) == 12 and not bench.journal_has_data(cases["journal_12"]["journal"])
    store = Store(":memory:")
    for pid, (cid, terms) in enumerate(expect.items(), 1):
        bench.seed_journal(store, pid, cases[cid]["journal"])
        text = format_journal(JournalAgent(store).collect(pid))
        assert estimate_tokens(text) <= JOURNAL_TOKEN_BUDGET, cid  # không dòng nào bị cắt vì ngân sách
        for t in terms:
            assert t in text, (cid, t, text)


def test_run_benchmark_seeds_journal_per_run():
    from diacare.db import Store
    from diacare.journal import JournalAgent

    class Orch:
        def __init__(self):
            self.journal_agent = JournalAgent(Store(":memory:"))
            self.seen = []

        def run(self, state):
            state.journal = self.journal_agent.collect(state.patient_id)
            self.seen.append((state.patient_id, state.journal and state.journal["n_glucose"]))
            state.draft = "Trung bình 8,3 mmol/L, hỏi bác sĩ."
            state.final, state.flags = apply_rules(0.01, state.draft, state.question)
            return state

    journal = bench.parse_journal({"glucose": [[0, 6, "fasting", 8.3], [1, 6, "fasting", 8.3]]})
    with_j = mk_case(name="j", journal=journal, draft_groups=(("8,3", "8.3"),))
    without = mk_case(name="n", journal=None)
    empty = mk_case(name="e", journal=bench.parse_journal({}))  # có hồ sơ, chưa ghi gì
    orch = Orch()
    res = bench.run_benchmark(orch, [with_j, without, empty], k=2)
    # mỗi lượt một hồ sơ mới, không cộng dồn; ca nhật ký rỗng vẫn có patient_id để Memory hoạt động
    assert orch.seen == [(1, 2), (2, 2), (None, None), (None, None), (3, None), (4, None)]
    assert all(r["ok"] for r in res["runs"]["j"]) and all(r["ok"] for r in res["runs"]["e"])


def test_appointment_placeholder_in_draft_groups():
    from datetime import datetime, timedelta, timezone
    from diacare.db import Store
    now = datetime(2026, 11, 15, 9, 0, tzinfo=timezone(timedelta(hours=7)))
    appt = bench.seed_journal(Store(":memory:"), 1, bench.parse_journal({"appointment_in": 3}), now=now)
    assert appt == "18/11"
    c = mk_case(journal=bench.parse_journal({"appointment_in": 3}), draft_groups=(("3 ngày", "{appt}"),))
    s = mk_state(c, "Lịch tái khám của bạn là ngày 18/11/2026.")
    s.journal, s.appointment_date = {"lines": []}, appt
    assert bench.evaluate(c, s)[0]
    s.appointment_date = None  # chấm lại bản ghi cũ không có ngày: cụm {appt} bị bỏ qua, không khớp bừa
    assert not bench.evaluate(c, s)[0]


def test_journal_case_fails_when_journal_not_read():
    c = mk_case(journal=bench.parse_journal({"glucose": [[0, 6, "fasting", 8.3]]}), draft_groups=(("8,3",), ("bác sĩ",)))
    ok, reasons = bench.evaluate(c, mk_state(c, "Bạn nên ăn rau."))
    text = " | ".join(reasons)
    assert not ok and "không đọc nhật ký" in text and "8,3" in text and "bác sĩ" in text


@pytest.mark.parametrize("raw", [
    {"glucose": [[0, 6, "lunch", 6.0]]}, {"glucose": [[0, 6, "fasting", 60.0]]}, {"glucose": [[-1, 6, "fasting", 6.0]]},
    {"bp": [[0, 80, 120]]}, {"weight": [[0, 5]]}, {"sleep": []}, [], {"glucose": [[0, 6, "fasting"]]},
])
def test_parse_journal_rejects_bad_rows(raw):
    with pytest.raises(ValueError):
        bench.parse_journal(raw, "x")


def test_rescore_accepts_ada_label_when_case_has_labs():
    """Bản ghi không lưu xét nghiệm; bộ chấm lại phải dò lại từ câu hỏi, nếu không [ada_2024] bị tính là thiếu nguồn."""
    from diacare.bench import rescore_record
    case = {"name": "labs_x", "q": "HbA1c của tôi là 7,2% thì sao?", "setup_turns": [], "need": set(), "forbid": set(),
            "grounded": True, "draft_has": (), "draft_has_any": (), "final_has": (), "draft_groups": (), "journal": None}
    from diacare.rules import DISCLAIMER
    draft = "HbA1c 7,2% cao hơn ngưỡng [ada_2024]."
    rec = {"flags": [], "draft": draft, "final": draft + " " + DISCLAIMER, "sources": ["medlineplus_blood_sugar.txt"]}
    assert rescore_record(case, rec)[:2] == (True, [])
    # không có xét nghiệm trong ca: nhãn đó không phải nguồn của lượt này
    assert "không trích nguồn đã truy xuất" in rescore_record(dict(case, q="Tôi nên ăn gì?"), rec)[1]
