import argparse
import json

from diacare.factory import build_orchestrator
from diacare.rules import risk_band
from diacare.samples import LOW_RISK
from diacare.state import State


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", help="đường dẫn file JSON hồ sơ (21 đặc trưng BRFSS)")
    args = ap.parse_args()
    if args.profile:
        with open(args.profile, encoding="utf-8") as f:
            profile = json.load(f)
    else:
        profile = LOW_RISK
    orch = build_orchestrator()
    history = []
    print("DiaCare-MAS V1. Gõ câu hỏi, 'q' để thoát.")
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() == "q":
            break
        if not q:
            continue
        state = orch.run(State(question=q, profile=profile, history=history))
        history = state.history
        band = risk_band(state.risk) if state.risk is not None else "chưa tính"
        print(f"\n[nguy cơ: {band}] [flags: {state.flags}]\n{state.final}\n")


if __name__ == "__main__":
    main()
