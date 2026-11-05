"""Dựng bảng dinh dưỡng món/nguyên liệu Việt Nam từ USDA FoodData Central (SR Legacy, 2018-04).

Số liệu dinh dưỡng (trên 100 g) lấy NGUYÊN từ USDA; tên tiếng Việt và khẩu phần là ước lượng
của nhóm dự án (đánh dấu "estimated": true). Chạy lại:
    python tools/build_vn_foods.py <thư mục CSV SR Legacy> data/nutrition/vn_foods.json
"""
import csv
import json
import sys
import unicodedata
from pathlib import Path

# id chất dinh dưỡng trong nutrient.csv của FDC -> (khoá, tên mong đợi để tự kiểm tra)
NUTRIENTS = {
    1008: ("kcal", "Energy"),
    1005: ("carb_g", "Carbohydrate, by difference"),
    1079: ("fiber_g", "Fiber, total dietary"),
    2000: ("sugar_g", "Sugars, Total"),
    1003: ("protein_g", "Protein"),
    1004: ("fat_g", "Total lipid (fat)"),
}

# (tên VN, các tên khác, mô tả USDA chính xác, khẩu phần, gam/khẩu phần)
FOODS = [
    ("cơm trắng", ["cơm", "gạo trắng"], "Rice, white, long-grain, regular, enriched, cooked", "1 bát", 150),
    ("cơm gạo lứt", ["gạo lứt"], "Rice, brown, long-grain, cooked (Includes foods for USDA's Food Distribution Program)", "1 bát", 150),
    ("xôi", ["gạo nếp", "nếp"], "Rice, white, glutinous, unenriched, cooked", "1 gói", 150),
    ("bún", ["phở", "bánh phở", "hủ tiếu"], "Rice noodles, cooked", "1 bát (phần bánh)", 200),
    ("miến khô", ["miến"], "Noodles, chinese, cellophane or long rice (mung beans), dehydrated", "1 nắm khô", 50),
    ("bánh mì", ["bánh mì que", "bánh mì Pháp"], "Bread, french or vienna (includes sourdough)", "1 ổ", 80),
    ("khoai lang luộc", ["khoai lang"], "Sweet potato, cooked, boiled, without skin", "1 củ vừa", 130),
    ("khoai tây luộc", ["khoai tây"], "Potatoes, boiled, cooked in skin, flesh, without salt", "1 củ vừa", 150),
    ("ngô luộc", ["bắp", "bắp luộc", "ngô"], "Corn, sweet, yellow, cooked, boiled, drained, without salt", "1 bắp (phần hạt)", 100),
    ("cháo yến mạch", ["yến mạch"], "Cereals, oats, regular and quick, unenriched, cooked with water (includes boiling and microwaving), without salt", "1 bát", 230),
    ("mì gói", ["mì tôm", "mì ăn liền"], "Soup, ramen noodle, any flavor, dry", "1 gói", 75),
    ("thịt gà", ["ức gà", "gà"], "Chicken, broilers or fryers, breast, meat only, cooked, roasted", "1 phần", 100),
    ("thịt lợn nạc", ["thịt heo nạc", "thịt lợn", "thịt heo"], "Pork, fresh, loin, whole, separable lean only, cooked, roasted", "1 phần", 100),
    ("thịt bò", ["bò"], "Beef, ground, 90% lean meat / 10% fat, patty, cooked, broiled", "1 phần", 100),
    ("cá rô phi", ["cá"], "Fish, tilapia, cooked, dry heat", "1 phần", 100),
    ("trứng gà luộc", ["trứng", "trứng gà"], "Egg, whole, cooked, hard-boiled", "1 quả", 50),
    ("đậu phụ", ["đậu hũ", "tàu hũ"], "Tofu, raw, firm, prepared with calcium sulfate", "1 bìa", 100),
    ("tôm", ["tôm luộc"], "Crustaceans, shrimp, cooked", "1 phần", 100),
    ("sữa tươi", ["sữa bò", "sữa"], "Milk, whole, 3.25% milkfat, with added vitamin D", "1 ly", 240),
    ("sữa chua", ["sữa chua không đường", "yaourt"], "Yogurt, plain, whole milk", "1 hộp", 100),
    ("sữa đặc", ["sữa đặc có đường"], "Milk, canned, condensed, sweetened", "1 thìa canh", 20),
    ("sữa đậu nành", ["sữa đậu"], "Soymilk, original and vanilla, unfortified", "1 ly", 240),
    ("rau muống", ["rau muống luộc"], "Water convolvulus, cooked, boiled, drained, without salt", "1 đĩa", 100),
    ("bắp cải", ["cải bắp"], "Cabbage, cooked, boiled, drained, without salt", "1 đĩa", 100),
    ("cà rốt", ["cà rốt luộc"], "Carrots, cooked, boiled, drained, without salt", "1 đĩa", 100),
    ("bông cải xanh", ["súp lơ xanh", "bông cải"], "Broccoli, cooked, boiled, drained, without salt", "1 đĩa", 100),
    ("cà chua", [], "Tomatoes, red, ripe, raw, year round average", "1 quả", 120),
    ("dưa chuột", ["dưa leo"], "Cucumber, with peel, raw", "1 quả", 150),
    ("bí đỏ", ["bí ngô"], "Pumpkin, cooked, boiled, drained, without salt", "1 bát", 150),
    ("mướp đắng", ["khổ qua"], "Balsam-pear (bitter gourd), pods, cooked, boiled, drained, without salt", "1 đĩa", 100),
    ("giá đỗ", ["giá"], "Mung beans, mature seeds, sprouted, raw", "1 nắm", 50),
    ("chuối", [], "Bananas, raw", "1 quả", 120),
    ("cam", [], "Oranges, raw, all commercial varieties", "1 quả", 130),
    ("táo", [], "Apples, raw, with skin (Includes foods for USDA's Food Distribution Program)", "1 quả", 180),
    ("xoài", [], "Mangos, raw", "1 quả (phần thịt)", 200),
    ("đu đủ", [], "Papayas, raw", "1 miếng", 150),
    ("dưa hấu", [], "Watermelon, raw", "1 miếng", 300),
    ("nho", [], "Grapes, red or green (European type, such as Thompson seedless), raw", "1 chùm nhỏ", 100),
    ("bưởi", [], "Pummelo, raw", "3 múi", 100),
    ("sầu riêng", [], "Durian, raw or frozen", "1 múi", 100),
    ("mít", [], "Jackfruit, raw", "1 phần", 100),
    ("vải", ["trái vải"], "Litchis, raw", "10 quả", 100),
    ("nhãn", [], "Longans, raw", "1 phần", 100),
    ("ổi", [], "Guavas, common, raw", "1 quả", 100),
    ("nước cam", ["nước cam vắt"], "Orange juice, raw (Includes foods for USDA's Food Distribution Program)", "1 ly", 240),
    ("đường", ["đường trắng", "đường kính"], "Sugars, granulated", "1 thìa cà phê", 5),
    ("mật ong", [], "Honey", "1 thìa canh", 21),
    ("đậu phộng", ["lạc", "đậu phộng rang"], "Peanuts, all types, dry-roasted, without salt", "1 nắm", 30),
    ("hạt điều", [], "Nuts, cashew nuts, dry roasted, without salt added", "1 nắm", 30),
]

# Nước ngọt có ga: SR Legacy không có cola thường, thử lần lượt các mô tả này.
SODA_CANDIDATES = [
    "Beverages, carbonated, cola, regular",
    "Carbonated beverage, cola, contains caffeine",
    "Beverages, carbonated, cola, without caffeine",
    "Beverages, carbonated, lemon-lime soda, no caffeine",
    "Beverages, carbonated, orange",
]


def strip_accents(s):
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def main(csv_dir, out_path):
    d = Path(csv_dir)
    names = {int(r["id"]): r["name"] for r in csv.DictReader(open(d / "nutrient.csv", encoding="utf-8"))}
    for nid, (_, expected) in NUTRIENTS.items():
        assert names.get(nid) == expected, f"nutrient {nid}: '{names.get(nid)}' != '{expected}'"

    by_desc = {r["description"]: int(r["fdc_id"]) for r in csv.DictReader(open(d / "food.csv", encoding="utf-8"))}
    foods = list(FOODS)
    soda = next((c for c in SODA_CANDIDATES if c in by_desc), None)
    if soda:
        foods.append(("nước ngọt có ga", ["nước ngọt", "coca", "pepsi", "soda"], soda, "1 lon", 330))
    missing = [f[2] for f in foods if f[2] not in by_desc]
    assert not missing, f"không thấy mô tả USDA: {missing}"
    wanted = {by_desc[f[2]] for f in foods}

    values = {fid: {} for fid in wanted}
    with open(d / "food_nutrient.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            fid, nid = int(r["fdc_id"]), int(r["nutrient_id"])
            if fid in wanted and nid in NUTRIENTS:
                values[fid][NUTRIENTS[nid][0]] = round(float(r["amount"]), 2)

    rows = []
    for vn, aliases, desc, portion, grams in foods:
        fid = by_desc[desc]
        per100 = {key: values[fid].get(key) for key, _ in NUTRIENTS.values()}
        names_all = [vn] + aliases
        rows.append({
            "name": vn,
            "aliases": sorted(set(names_all + [strip_accents(n) for n in names_all]) - {vn}),
            "usda_fdc_id": fid,
            "usda_description": desc,
            "per_100g": per100,
            "portion": {"label": portion, "grams": grams, "estimated": True},
        })
    out = {
        "source": "USDA FoodData Central, SR Legacy (April 2018), https://fdc.nal.usda.gov/download-datasets/",
        "note": "Giá trị trên 100 g lấy từ USDA. Tên tiếng Việt, ánh xạ món và khẩu phần là ước lượng của dự án, chỉ dùng cho học tập.",
        "foods": rows,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} món -> {out_path}; nước ngọt: {soda or 'KHÔNG CÓ'}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
