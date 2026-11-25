"""Chấm lại phép kiểm tra con số của Critic trên bản nháp đã lưu của một lần chạy benchmark, với Critic hiện tại.

Lần chạy cũ không lưu ngữ cảnh đã đưa cho Advisor (chỉ lưu tên tệp nguồn), nên ngữ cảnh ở đây được DỰNG LẠI GẦN ĐÚNG:
câu hỏi + toàn văn các tệp nguồn đã truy hồi (rộng hơn các đoạn thật sự đưa cho mô hình) + bảng dinh dưỡng của câu hỏi
(nếu là câu hỏi dinh dưỡng) + khối xét nghiệm của câu hỏi. Vì ngữ cảnh rộng hơn thật, kết quả nghiêng về "có căn cứ";
hai lần chạy được chấm cùng một cách nên so được với nhau.

    python tools/critic_rescore.py docs/results/A/results.json [docs/results/B/results.json ...] [--category diet ...]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from diacare.critic import check_grounding  # noqa: E402
from diacare.labs import classify, format_labs, parse_lab_text  # noqa: E402
from diacare.nutrition import NutritionAgent, format_table, is_nutrition_question, load_foods  # noqa: E402


def contexts(cases_path):
    cases = {c["id"]: c for c in json.loads(Path(cases_path).read_text(encoding="utf-8"))}
    foods = NutritionAgent(load_foods(ROOT / "data" / "nutrition" / "vn_foods.json"))
    return cases, foods


def rebuild(case, sources, foods):
    turns = [t if isinstance(t, str) else json.dumps(t, ensure_ascii=False) for t in case.get("turns") or []]
    q = case.get("q") or turns[-1]  # ca nhiều lượt: câu hỏi chấm là lượt cuối
    docs = []
    for name in dict.fromkeys(sources or []):
        p = ROOT / "kb" / name
        if p.exists():
            docs.append({"source": name, "text": p.read_text(encoding="utf-8")})
    analysis = foods.analyze(q)
    nutrition = format_table(analysis) if analysis and is_nutrition_question(q, analysis) else ""
    labs = parse_lab_text(q)
    lab_text = format_labs(classify(labs)) if labs else ""
    # lượt hội thoại trước của ca (ca memory): thay cho khối bộ nhớ và lịch sử thật
    history = [{"role": "user", "content": t} for t in turns[:-1]]
    return {"question": q, "docs": docs, "nutrition_text": nutrition, "lab_text": lab_text, "history": history}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("results", nargs="+")
    ap.add_argument("--cases", default=str(ROOT / "eval" / "cases.json"))
    ap.add_argument("--category", nargs="*")
    ap.add_argument("--show", action="store_true", help="in từng lượt bị gắn cờ")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    cases, foods = contexts(args.cases)
    for path in args.results:
        (model, v), = json.loads(Path(path).read_text(encoding="utf-8"))["results"].items()
        turns = flagged = numbers = 0
        for cid, runs in v["runs"].items():
            if cid not in cases or (args.category and cases[cid]["category"] not in args.category):
                continue
            for i, r in enumerate(runs):
                g = check_grounding(r.get("draft") or "", rebuild(cases[cid], r.get("sources"), foods))
                turns += 1
                numbers += g["numbers"]
                if g["unsupported_numbers"]:
                    flagged += 1
                    if args.show:
                        print(f"  {cid}#{i + 1}: {g['unsupported_numbers']}")
        print(f"{path} ({model}): {turns} lượt, {numbers} số có đơn vị/thập phân, {flagged} lượt có số không tìm "
              "thấy trong ngữ cảnh dựng lại")


if __name__ == "__main__":
    main()
