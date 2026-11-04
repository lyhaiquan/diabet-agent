import argparse
import json

from diacare.factory import build_orchestrator
from diacare.samples import LOW_RISK
from diacare.state import State


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", help="đường dẫn file JSON hồ sơ (21 đặc trưng BRFSS)")
    args = ap.parse_args()
    profile = json.load(open(args.profile, encoding="utf-8")) if args.profile else LOW_RISK
    orch = build_orchestrator()
    history = []
    print("DiaCare-MAS V1. Gõ câu hỏi, 'q' để thoát.")
    while (q := input("> ").strip()) and q.lower() != "q":
        state = orch.run(State(question=q, profile=profile, history=history))
        history = state.history
        print(f"\n[nguy cơ: {state.risk}] [flags: {state.flags}]\n{state.final}\n")


if __name__ == "__main__":
    main()
