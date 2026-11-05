"""Agent dinh dưỡng: nhận diện món ăn Việt trong câu hỏi, tính carb/kcal từ bảng USDA."""
import json
import re
import unicodedata
from pathlib import Path

SOURCE = "usda_fdc"
NUTRIENT_KEYS = ("kcal", "carb_g", "fiber_g", "sugar_g", "protein_g", "fat_g")

PORTION_UNITS = {"bat", "chen", "to", "qua", "trai", "lon", "ly", "coc", "dia", "mieng", "goi", "o",
                 "cu", "thia", "muong", "nam", "hop", "phan", "bap", "mui", "lat"}
GRAM_UNITS = {"g", "gr", "gram", "gam"}
_NUM = r"\d+(?:[.,]\d+)?"
NUM_RE = re.compile(rf"^{_NUM}$")
GLUED_RE = re.compile(rf"^({_NUM})([^\d.,]+)$")

# Từ khóa có dấu (so khớp theo ranh giới từ) và không dấu (chỉ cụm nhiều từ, tránh "an" quá chung)
NUTRITION_KEYWORDS = ("ăn", "uống", "món", "thực đơn", "bữa", "carb", "tinh bột", "calo", "kcal",
                      "khẩu phần", "chế độ ăn", "đồ ăn", "thức ăn")
NUTRITION_KEYWORDS_ASCII = ("an uong", "an gi", "mon an", "thuc don", "bua an", "bua sang", "bua trua",
                            "bua toi", "che do an", "do an", "thuc an", "tinh bot", "calo", "carb",
                            "kcal", "khau phan")


def load_foods(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))["foods"]


def _norm(text):
    return unicodedata.normalize("NFC", text).lower()


def strip_accents(text):
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def has_diacritics(text):
    return strip_accents(unicodedata.normalize("NFC", text)) != unicodedata.normalize("NFC", text)


def _word_re(name):
    return re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")


def _contains_word(text, word):
    return _word_re(word).search(text) is not None


def _is_nutrient_query(food, text, start, end):
    """'bao nhiêu đường' / 'đường huyết' là chất/chỉ số, không phải thìa đường."""
    if food["name"] != "đường":
        return False
    before = strip_accents(text[:start]).rstrip()
    after = strip_accents(text[end:]).lstrip()
    return before.endswith(("bao nhieu", "luong")) or after.startswith("huyet")


def _num(token):
    return float(token.replace(",", "."))


def _qty_token(token):
    """Số (1, 1,5, 0.5) hoặc 'nửa' (đã bỏ dấu: 'nua') = 0.5; không phải số thì None."""
    if NUM_RE.match(token):
        return _num(token)
    return 0.5 if token == "nua" else None


def _fmt(x):
    return f"{x:g}"


class NutritionAgent:
    def __init__(self, foods):
        self.foods = foods
        self._entries = []  # (tên chuẩn hóa, tên không dấu, food)
        for food in foods:
            main_accented = has_diacritics(food["name"])
            seen = set()
            for raw in [food["name"], *food.get("aliases", [])]:
                name = _norm(raw).strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                self._entries.append((name, strip_accents(name), food, main_accented))

    def find_foods(self, question):
        return [(f, s, e) for f, s, e, _ in self._find(question)]

    def _find(self, question):
        q = _norm(question)
        accented = has_diacritics(q)
        cands = []
        for name, plain, food, main_accented in self._entries:
            if accented:
                # tên có dấu luôn dùng; tên ASCII chỉ dùng khi tên chính của món cũng không dấu (vd "cam")
                # (alias ASCII nhiều từ như "khoai lang" cũng hợp lệ: ít khi trùng từ khác)
                if has_diacritics(name) or not main_accented or len(name.split()) >= 2:
                    cands.append((name, name, food))
            else:
                cands.append((plain, name, food))
        # cùng độ dài: ưu tiên dạng có dấu để hiển thị đúng chính tả
        cands.sort(key=lambda c: (-len(c[0]), not has_diacritics(c[1])))
        spans, used = [], set()
        for name, display, food in cands:
            if id(food) in used:
                continue
            for m in _word_re(name).finditer(q):
                s, e = m.span()
                if any(s < us_e and us_s < e for _, us_s, us_e, _ in spans):
                    continue
                if _is_nutrient_query(food, q, s, e):
                    continue
                spans.append((food, s, e, display))
                used.add(id(food))
                break
        return sorted(spans, key=lambda x: x[1])

    def _quantity(self, q, start, food):
        """Trả (gram, from_portion, số_khẩu_phần)."""
        portion = food["portion"]["grams"]
        tokens = [strip_accents(t) for t in re.findall(r"\S+", q[:start])[-3:]]
        extra = 0.0
        if tokens and tokens[-1] == "ruoi":  # "1 bát rưỡi" = 1.5 bát
            extra, tokens = 0.5, tokens[:-1]
        tokens = tokens[-2:]
        if tokens:
            last = tokens[-1]
            glued = GLUED_RE.match(last)
            if glued and (glued.group(2) in GRAM_UNITS or glued.group(2) in PORTION_UNITS):
                qty, unit = _num(glued.group(1)), glued.group(2)
            elif last in GRAM_UNITS | PORTION_UNITS and len(tokens) == 2 and _qty_token(tokens[0]) is not None:
                qty, unit = _qty_token(tokens[0]), last
            elif _qty_token(last) is not None:
                qty, unit = _qty_token(last), None
            else:
                qty, unit = None, None
            if qty is not None and qty + extra > 0:
                qty += extra
                if unit in GRAM_UNITS:
                    return round(qty, 1), False, None
                return round(qty * portion, 1), True, qty
        return float(portion), True, 1

    def analyze(self, question):
        found = self._find(question)
        if not found:
            return None
        q = _norm(question)
        items = []
        for food, start, _, display in found:
            grams, from_portion, qty = self._quantity(q, start, food)
            item = {"name": display, "food": food["name"], "grams": grams, "from_portion": from_portion,
                    "portion_label": food["portion"]["label"], "portions": qty}
            for key in NUTRIENT_KEYS:
                v = food["per_100g"].get(key)
                item[key] = None if v is None else round(v * grams / 100, 1)
            items.append(item)
        totals = {}
        for key in NUTRIENT_KEYS:
            vals = [i[key] for i in items if i[key] is not None]
            totals[key] = round(sum(vals), 1) if vals else None
        return {"items": items, "totals": totals, "source": SOURCE}


def _num_or(value, missing="không có số liệu"):
    return missing if value is None else _fmt(value)


def format_table(result):
    lines = ["Bảng dinh dưỡng [usda_fdc] (USDA FoodData Central; khẩu phần là ước lượng):"]
    for i in result["items"]:
        label = ""
        if i["from_portion"] and i.get("portion_label"):
            qty = i.get("portions")
            label = f" ({i['portion_label']})" if qty in (None, 1) else f" ({_fmt(qty)} × {i['portion_label']})"
        sugar = "không có số liệu" if i["sugar_g"] is None else f"{_fmt(i['sugar_g'])} g"
        who = i["name"] if i.get("food", i["name"]) == i["name"] else f"{i['name']} (số liệu của {i['food']})"
        lines.append(f"- {who}: {_fmt(i['grams'])} g{label} -> {_num_or(i['kcal'])} kcal, "
                     f"carb {_num_or(i['carb_g'])} g, xơ {_num_or(i['fiber_g'])} g, đường {sugar}")
    t = result["totals"]
    sugar = "không có số liệu" if t["sugar_g"] is None else f"{_fmt(t['sugar_g'])} g"
    lines.append(f"Tổng: {_num_or(t['kcal'])} kcal, carb {_num_or(t['carb_g'])} g, "
                 f"xơ {_num_or(t['fiber_g'])} g, đường {sugar}")
    return "\n".join(lines)


def is_nutrition_question(question, analysis):
    if analysis is not None:
        return True
    q = _norm(question)
    if has_diacritics(q):
        return any(_contains_word(q, k) for k in NUTRITION_KEYWORDS)
    return any(_contains_word(q, k) for k in NUTRITION_KEYWORDS_ASCII)
