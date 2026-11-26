# -*- coding: utf-8 -*-
"""Chèn trích dẫn số [n] kiểu IEEE và dựng lại danh mục tài liệu tham khảo khi build báo cáo.

apply(md) trả về markdown mới:
  - mỗi tài liệu được đánh số theo thứ tự xuất hiện đầu tiên trong thân bài;
  - [n] chèn ngay sau từ khoá đầu tiên nhắc tới tài liệu đó (không chèn vào tiêu đề, hình, khối mã);
  - trích dẫn kiểu "(Li và cộng sự, 2010)" được đổi thành [n];
  - danh mục cuối bài viết lại: [n] Tác giả, "Tiêu đề," Nguồn, năm. ("et al.", dấu phẩy trong ngoặc kép).
"""
import re

# (regex nhận diện mục trong danh mục, regex từ khoá để chèn trích dẫn trong thân bài)
CITES = [
    (r"ReAct", r"ReAct"),
    (r"Retrieval-Augmented", r"\bRAG\b"),
    (r"MemGPT", r"MemGPT"),
    (r"Lost in the Middle", r"Lost in the Middle"),
    (r"τ-bench", r"τ-bench"),
    (r"Evaluating Large Language Models Trained on Code", r"Pass@3"),
    (r"Building effective agents", r"\bworkflow\b"),
    (r"context engineering", r"context engineering|Context Slicing"),
    (r"Standards of Care", r"ADA 2024"),
    (r"Diabetes Health Indicators|BRFSS 2015", r"BRFSS 2015"),
    (r"Qwen2\.5", r"[Qq]wen2\.5|Qwen"),
    (r"Sentence-BERT", r"MiniLM"),
    (r"Reciprocal Rank", r"RRF"),
    (r"MedlinePlus", r"MedlinePlus|USDA"),
    (r"PrimeKG|Precision Medicine", r"PrimeKG"),
    (r"Graph Convolutional", r"R-?GCN"),
    (r"Embedding Entities", r"DistMult|TransE"),
    (r"\"Knowledge Graphs\"", r"đồ thị tri thức"),
    (r"Cypher", r"Cypher"),
    (r"Reinforcement Learning: An Introduction", r"Q-learning"),
    (r"Contextual-Bandit", r"LinUCB"),
    (r"Self-Normalized", r"SNIPS"),
    (r"Annual Survey Data|2023 Annual", r"BRFSS 2023"),
    (r"National Health and Nutrition", r"NHANES"),
    (r"ADAP Learning", r"Pima"),
    (r"Robust Speech Recognition", r"\bWhisper"),
    (r"PhoWhisper", r"PhoWhisper"),
    (r"JSON Web Token", r"JWT"),
    (r"scrypt", r"scrypt"),
    (r"STEPwise|STEPS", r"STEPS"),
    (r"Likelihood Prediction of Diabetes", r"UCI 529"),
    (r"Transforming Classifier Scores", r"isotonic"),
    (r"Scikit-learn", r"scikit-learn|sklearn"),
]

# trích dẫn tác giả-năm trong thân bài -> từ khoá của mục tương ứng trong CITES
AUTHOR_YEAR = [
    ("Chandak", "PrimeKG"), ("Schlichtkrull", "R-?GCN"), ("Yang và cộng sự", "DistMult"),
    ("Li và cộng sự", "LinUCB"), ("Swaminathan", "SNIPS"),
]

REF_HEAD = re.compile(r"^# Tài liệu [Tt]ham khảo.*$", re.M)


def _cites_index(kw):
    return next(i for i, (_, k) in enumerate(CITES) if kw in k.split("|"))


def _author_year(md):
    """(Chandak và cộng sự, 2023) -> dấu ⟦i⟧, đổi thành [n] sau khi đánh số."""
    md = md.replace(
        "(Sutton và Barto, chương 2; Li và cộng sự, 2010)",
        "(chương 2 của ⟦%d⟧; ⟦%d⟧)" % (_cites_index("Q-learning"), _cites_index("LinUCB")),
    )
    for name, kw in AUTHOR_YEAR:
        md = re.sub(r"[ ]?\(%s[^()]*?, \d{4}\)" % name, " ⟦%d⟧" % _cites_index(kw), md)
    return md


def _split_refs(md):
    m = REF_HEAD.search(md)
    if not m:
        return md, None, None, ""
    rest = md[m.end():]
    nxt = re.search(r"^# ", rest, re.M)
    end = m.end() + (nxt.start() if nxt else len(rest))
    items = []
    for line in md[m.end():end].splitlines():
        mm = re.match(r"\s*\d+\.\s+(.*\S)\s*$", line)
        if mm:
            items.append(mm.group(1))
    return md[:m.start()], m.group(0), items, md[end:]


def _clean(t):
    t = t.replace("**", "")
    t = t.replace(" và cộng sự", " et al.")
    t = t.replace('",', ',"')
    return t.strip()


def _prose_lines(lines):
    """Chỉ số các dòng văn xuôi: không tiêu đề, hình, khối mã, trích dẫn khối, dòng kẻ bảng."""
    ok, fence, started = [], False, False
    for i, line in enumerate(lines):
        s = line.lstrip()
        if s.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if s.startswith("# "):
            started = True
        if not started or not s:
            continue
        if s[0] in "#!>$:<" or s.startswith("{{") or s.startswith("|-") or s.startswith("| -"):
            continue
        ok.append(i)
    return ok


def _spot(line, m):
    """Vị trí chèn [n] cho một kết quả khớp; nếu nằm trong code span hay công thức thì dời ra sau."""
    pos = m.end()
    if line[:m.start()].count("`") % 2 == 1:
        j = line.find("`", pos)
        if j < 0:
            return None
        pos = j + 1
    pre = line[:pos].replace("\\$", "")
    if pre.count("$") % 2 == 1:
        j = line.find("$", pos)
        if j < 0:
            return None
        pos = j + 1
    return pos


def apply(md):
    md = _author_year(md)
    head, rhead, items, tail = _split_refs(md)
    if not items:
        return re.sub(r" ?⟦\d+⟧", "", md)
    lines = head.split("\n")
    prose = _prose_lines(lines)

    item_of = {}                      # chỉ số CITES -> chỉ số mục trong danh mục
    for ci, (ref_re, _) in enumerate(CITES):
        idx = next((k for k, t in enumerate(items) if re.search(ref_re, t, re.I)), None)
        if idx is not None:
            item_of[ci] = idx

    first, ins = {}, {}               # mục -> (dòng, vị trí) đầu tiên; dòng -> [(vị trí, mục)]
    for ci, idx in item_of.items():
        pat = re.compile(CITES[ci][1])
        found = None
        for i in prose:
            for m in pat.finditer(lines[i]):
                pos = _spot(lines[i], m)
                if pos is not None:
                    found = (i, pos)
                    break
            if found:
                break
        if found:
            first[idx] = found
            ins.setdefault(found[0], []).append((found[1], idx))
    for i, line in enumerate(lines):  # dấu ⟦i⟧: mỗi lần xuất hiện đều là một trích dẫn
        for m in re.finditer(r"⟦(\d+)⟧", line):
            idx = item_of.get(int(m.group(1)))
            if idx is not None:
                first[idx] = min(first.get(idx, (i, m.start())), (i, m.start()))

    num = {idx: n + 1 for n, idx in enumerate(sorted(first, key=lambda k: first[k]))}
    for i, lst in ins.items():
        line = lines[i]
        for pos, idx in sorted(lst, reverse=True):
            line = line[:pos] + " \\[%d\\]" % num[idx] + line[pos:]
        lines[i] = line
    for k in range(len(items)):       # mục chưa có điểm chèn: xếp cuối, vẫn đánh số
        if k not in num:
            num[k] = len(num) + 1
            print("  [ieee] chưa trích dẫn trong thân bài:", items[k][:60])

    body = "\n".join(lines)
    def mark(m):
        idx = item_of.get(int(m.group(1)))
        return "" if idx is None else "\\[%d\\]" % num[idx]

    body = re.sub(r"⟦(\d+)⟧", mark, body)
    body = body.replace("; )", ")")
    body = re.sub(r"(\\\[\d+\\\])(?:\s*\1)+", r"\1", body)       # [n] [n] -> [n]

    out = ['::: {custom-style="Reference"}']
    for k in sorted(num, key=lambda k: num[k]):
        out.append("\\[%d\\] %s\n" % (num[k], _clean(items[k])))
    out.append(":::")
    return body + "\n" + rhead + "\n\n" + "\n".join(out) + "\n" + tail
