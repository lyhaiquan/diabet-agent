import argparse
import json

from diacare.factory import build_orchestrator, open_store
from diacare.rules import risk_band, validate_profile
from diacare.samples import LOW_RISK
from diacare.state import State

HELP = "Lệnh: /patients, /history, /stats, /q (hoặc q) để thoát. Gõ câu hỏi để được tư vấn."


def _pick_patient(args, store, print_fn):
    if args.profile:
        try:
            with open(args.profile, encoding="utf-8") as f:
                profile = json.load(f)
        except (OSError, ValueError) as exc:
            print_fn(f"Không đọc được file hồ sơ: {exc}")
            return None
        if not isinstance(profile, dict):
            print_fn("Hồ sơ không hợp lệ: file JSON phải là một đối tượng.")
            return None
        errors = validate_profile(profile)
        if errors:
            print_fn("Hồ sơ không hợp lệ: " + "; ".join(errors))
            return None
        return store.get_patient(store.save_patient(args.name, profile))
    if args.patient is not None:
        patient = store.get_patient(args.patient)
        if patient is None:
            print_fn(f"Không tìm thấy bệnh nhân có ID {args.patient}.")
        return patient
    patients = store.list_patients()
    if patients:
        return patients[0]
    return store.get_patient(store.save_patient("Mẫu", LOW_RISK))


def _print_patients(store, print_fn):
    for p in store.list_patients():
        print_fn(f"  #{p['id']} {p['name']}")


def _print_history(store, session_id, print_fn, n=10):
    msgs = store.get_history(session_id)[-n:]
    if not msgs:
        print_fn("(chưa có tin nhắn)")
    for m in msgs:
        print_fn(f"  {m['role']}: {m['content']}")


def _print_stats(store, print_fn):
    for key, value in store.run_stats().items():
        print_fn(f"  {key}: {value}")


def _ask(orch, store, session_id, patient, question, print_fn):
    history = store.get_history(session_id)
    state = orch.run(State(question=question, profile=patient["profile"], history=history,
                           patient_id=patient["id"]))
    store.add_message(session_id, "user", question)
    store.add_message(session_id, "assistant", state.final)
    band = risk_band(state.risk) if state.risk is not None else "chưa tính"
    sources = ", ".join(d["source"] for d in state.docs) or "(không có)"
    print_fn(f"\n[nguy cơ: {band}] [flags: {state.flags}]\nNguồn: {sources}")
    if state.usage:
        u = state.usage
        print_fn(
            f"Token: prompt={u.get('prompt_tokens')} completion={u.get('completion_tokens')} "
            f"thời gian={u.get('seconds')}s num_ctx={u.get('num_ctx')}"
        )
    print_fn(f"{state.final}\n")


def main(argv=None, input_fn=input, print_fn=print):
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", type=int, help="ID bệnh nhân đã lưu")
    ap.add_argument("--profile", help="đường dẫn file JSON hồ sơ (21 đặc trưng BRFSS)")
    ap.add_argument("--name", default="CLI", help="tên bệnh nhân khi nhập --profile")
    args = ap.parse_args(argv)
    store = open_store()
    try:
        patient = _pick_patient(args, store, print_fn)
        if patient is None:
            return 1
        session_id = store.start_session(patient["id"])
        orch = build_orchestrator(store=store, session_id=session_id)
        print_fn(f"DiaCare-MAS. Bệnh nhân #{patient['id']} {patient['name']}. {HELP}")
        while True:
            try:
                line = input_fn("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line.lower() in ("q", "/q"):
                break
            if line == "/patients":
                _print_patients(store, print_fn)
            elif line == "/history":
                _print_history(store, session_id, print_fn)
            elif line == "/stats":
                _print_stats(store, print_fn)
            else:
                _ask(orch, store, session_id, patient, line, print_fn)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
