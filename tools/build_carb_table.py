"""Bảng tinh bột (carb g/100 g) cho 45 lớp món của Calo Khay -> data/nutrition/calo_khay_carb.csv

Nguồn số liệu: Nutrition5k (Thames et al., CVPR 2021), file ingredients_metadata.csv, cột carb(g) (g carb / g món),
theo bài báo lấy từ USDA FNDDS. Đây cũng là nguồn của cột kcal trong models/calories.csv của Calo Khay, nên carb và
kcal khớp nhau. Script chỉ ĐỌC con số carb từ file đó; trong script chỉ có TỈ LỆ pha trộn (giả định ghi rõ).

Mỗi món có hai giá trị:
  carb_per_100g   ước lượng chính
  carb_high       cận trên khi món có thêm phần tinh bột mà nguyên liệu chính không tính (đường kho, bột tẩm, bột
                  độn trong giò chả, vỏ nem). Với người tiểu đường, ước THẤP là chiều nguy hiểm, nên app hiển thị
                  khoảng [carb thấp, carb cao] chứ không chỉ một số.
Mỗi giá trị là hỗn hợp [(mục Nutrition5k, tỉ lệ khối lượng)], carb = tổng tỉ lệ x carb của mục.

    python tools/build_carb_table.py [--n5k D:/food-labeling/ref/nutrition5k_ingredients_metadata.csv]
                                     [--classes D:/CVision/Final_Project_Digital_Image_Processing/models/calories.csv]
"""
import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "nutrition" / "calo_khay_carb.csv"
N5K = Path("D:/food-labeling/ref/nutrition5k_ingredients_metadata.csv")
CLASSES = Path("D:/CVision/Final_Project_Digital_Image_Processing/models/calories.csv")

# Phần thêm vào (giả định tỉ lệ khối lượng), dùng cho cận trên
SAUCE = 0.10    # nước kho / sốt ngọt ~10% khối lượng món, tính như "barbecue sauce" (41% carb)
STARCH = 0.10   # bột độn trong giò, chả, xúc xích ~10%, tính như "corn starch"


def mix(*parts):
    return list(parts)


def plus(base, entry, share):
    """base (một mục) chiếm 1-share, phần thêm `entry` chiếm share."""
    return [(base, 1 - share), (entry, share)]


# lớp: (ước lượng chính, cận trên hoặc None = như chính, mức khớp, ghi chú)
MAP = {
    "rice": (mix(("white rice", 1)), None, "khớp", "phần lớn carb của khay; số gram cơm sai nhiều nhất, nên sửa tay"),
    "fried_tofu": (mix(("tofu", 1)), None, "chỉ nguyên liệu", "đậu chưa rán; rán không thêm carb đáng kể"),
    "betel_leaf_pork": (mix(("meatballs", 1)), None, "gần đúng", "thịt viên"),
    "bean_sprouts_bamboo": (mix(("bean sprouts", 1)), None, "chỉ nguyên liệu", ""),
    "minced_pork_corn": (mix(("ground pork", 40 / 244), ("corn", 204 / 244)), mix(("corn", 1)), "tính theo công thức",
                         "40 g thịt + 204 g ngô (công thức mytour.vn, như bảng kcal); cận trên coi như toàn ngô"),
    "bell_pepper_chicken": (mix(("chicken", 0.7), ("mixed vegetables", 0.3)), plus("chicken", "barbecue sauce", SAUCE),
                            "ước tính", "70% gà + 30% ớt chuông; cận trên nếu có sốt ngọt 10%"),
    "rolled_omelette": (mix(("omelets", 1)), None, "khớp", ""),
    "pumpkin": (mix(("pumpkins", 1)), None, "gần đúng", ""),
    "boiled_egg": (mix(("hard boiled eggs", 1)), None, "khớp", ""),
    "drink": (None, None, "không tính", "đồ uống không tính (trà sữa, nước ngọt có thể nhiều carb hơn cả khay)"),
    "coconut_braised_pork": (mix(("pork", 1)), plus("pork", "barbecue sauce", SAUCE), "chỉ nguyên liệu",
                             "chưa tính đường, nước dừa kho; cận trên tính nước kho ngọt 10%"),
    "chinese_sausage": (mix(("sausage", 1)), plus("sausage", "sugar", 0.15), "gần đúng",
                        "xúc xích kiểu Mỹ; lạp xưởng tẩm đường, cận trên tính 15% đường"),
    "fried_chicken": (mix(("fried chicken", 1)), mix(("chicken nuggets", 1)), "khớp",
                      "cận trên nếu tẩm bột dày (như gà viên chiên)"),
    "leafy_greens": (mix(("mixed greens", 1)), None, "gần đúng", ""),
    "pork_broccoli": (mix(("pork", 0.5), ("broccoli", 0.5)), mix(("broccoli", 1)), "ước tính", "50% thịt + 50% súp lơ"),
    "cutlet": (mix(("pork chops", 1)), mix(("chicken nuggets", 1)), "gần đúng", "cận trên nếu tẩm bột chiên xù"),
    "chayote": (mix(("chayote squash", 1)), None, "khớp", ""),
    "pork_floss": (mix(("jerky", 1)), plus("jerky", "sugar", 0.25), "ước tính",
                   "Nutrition5k không có chà bông; tính như thịt khô, cận trên thêm 25% đường"),
    "quail_egg": (mix(("eggs", 1)), None, "gần đúng", "trứng gà"),
    "egg_meatloaf": (mix(("eggs", 0.5), ("ground pork", 0.5)), mix(("eggs", 0.4), ("ground pork", 0.35),
                                                                   ("noodles", 0.25)),
                     "ước tính", "trứng + thịt; cận trên nếu có 25% miến"),
    "sausage": (mix(("sausage", 1)), plus("sausage", "corn starch", STARCH), "khớp", "cận trên nếu có 10% bột độn"),
    "potato": (mix(("potatoes", 1)), mix(("roasted potatoes", 1)), "gần đúng", "luộc; cận trên khi xào/chiên"),
    "soup": (mix(("chicken soup", 1)), mix(("mixed vegetables", 1)), "gần đúng",
             "dao động lớn theo loại canh; canh bí, khoai thì nhiều carb hơn"),
    "boiled_pork": (mix(("pork", 1)), None, "gần đúng", ""),
    "radish": (mix(("radishes", 1)), None, "khớp", ""),
    "braised_egg": (mix(("hard boiled eggs", 1)), plus("hard boiled eggs", "barbecue sauce", SAUCE), "chỉ nguyên liệu",
                    "chưa tính nước kho; cận trên tính nước kho ngọt 10%"),
    "water_spinach": (mix(("spinach (cooked)", 1)), None, "gần đúng", "rau khác loài"),
    "braised_fish": (mix(("fish", 1)), plus("fish", "barbecue sauce", SAUCE), "chỉ nguyên liệu",
                     "chưa tính đường, nước kho; cận trên tính nước kho ngọt 10%"),
    "pork_roll": (mix(("ham", 1)), plus("ham", "corn starch", STARCH), "gần đúng", "cận trên nếu có 10% bột độn"),
    "shrimp_spring_roll": (mix(("egg rolls", 1)), mix(("dumplings", 1)), "gần đúng",
                           "mục 'spring rolls' của Nutrition5k chỉ 4% carb (như cuốn tươi không bánh), quá thấp cho "
                           "nem rán có vỏ -> dùng 'egg rolls'; cận trên như bánh bao/há cảo"),
    "fried_egg": (mix(("fried eggs", 1)), None, "khớp", ""),
    "sweet_sour_chicken": (mix(("chicken nuggets", 1)), plus("chicken nuggets", "barbecue sauce", 0.25), "ước tính",
                           "gà tẩm bột chiên; cận trên tính 25% sốt chua ngọt"),
    "dog_meat_rua_man": (mix(("pork", 1)), plus("pork", "barbecue sauce", SAUCE), "ước tính",
                         "thịt kho riềng mẻ; cận trên tính nước sốt 10%"),
    "pork_with_tofu": (mix(("tofu", 0.6), ("ground pork", 0.4)), plus("tofu", "barbecue sauce", SAUCE), "ước tính",
                       "60% đậu + 40% thịt; cận trên tính sốt cà chua/ngọt 10%"),
    "silkworm_pupae": (mix(("pork", 1)), plus("pork", "barbecue sauce", SAUCE), "ước tính",
                       "Nutrition5k không có nhộng; món đạm, coi như ít carb; cận trên nếu rim ngọt"),
    "stir_fried_vegetables": (mix(("mixed vegetables", 1)), None, "chỉ nguyên liệu", ""),
    "fried_anchovy": (mix(("anchovies", 1)), plus("anchovies", "barbecue sauce", 0.15), "gần đúng",
                      "cá cơm rim thường ngọt; cận trên tính 15% nước rim"),
    "peanuts": (mix(("peanuts", 1)), None, "khớp", ""),
    "fried_shrimp": (mix(("shrimp", 1)), mix(("tempura", 1)), "chỉ nguyên liệu", "tôm chưa chiên; cận trên nếu tẩm bột"),
    "bean_sprouts_green_beans": (mix(("bean sprouts", 0.5), ("green beans", 0.5)), None, "chỉ nguyên liệu", ""),
    "cabbage": (mix(("cabbage", 1)), None, "khớp", ""),
    "fried_pork_skin": (mix(("pork", 1)), None, "gần đúng", "bì lợn gần như không có carb"),
    "fish_ball": (plus("fish", "corn starch", STARCH), plus("fish", "corn starch", 0.2), "ước tính",
                  "Nutrition5k không có cá viên; cá + 10-20% bột"),
    "stir_fried_gizzard": (mix(("chicken", 1)), plus("chicken", "barbecue sauce", SAUCE), "gần đúng",
                           "mề tính như thịt gà; cận trên nếu xào sốt ngọt"),
    "roasted_cinnamon_pork": (mix(("ground pork", 1)), plus("ground pork", "corn starch", STARCH), "gần đúng",
                              "chả quế; cận trên nếu có 10% bột độn"),
}


def carb(spec, src):
    return round(100 * sum(share * src[entry] for entry, share in spec), 1)


def describe(spec):
    return " + ".join(f"{share:.0%} {entry}" if share != 1 else entry for entry, share in spec)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n5k", type=Path, default=N5K)
    ap.add_argument("--classes", type=Path, default=CLASSES)
    args = ap.parse_args(argv)
    src = {r["ingr"]: float(r["carb(g)"]) for r in csv.DictReader(open(args.n5k, encoding="utf-8"))}
    classes = list(csv.DictReader(open(args.classes, encoding="utf-8-sig")))
    names = [c["class"] for c in classes]
    assert set(names) == set(MAP), set(names) ^ set(MAP)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        # kcal_per_100g chép nguyên từ models/calories.csv của Calo Khay (để tính lại kcal khi người dùng sửa món/gram)
        w.writerow(["class", "name_vi", "carb_per_100g", "carb_high", "kcal_per_100g", "match", "nutrition5k_mix",
                    "high_mix", "note"])
        for c in classes:
            base, high, match, note = MAP[c["class"]]
            kcal = c["kcal_per_100g"]
            if base is None:
                w.writerow([c["class"], c["name_vi"], "", "", kcal, match, "", "", note])
                continue
            lo = carb(base, src)
            hi = max(lo, carb(high, src)) if high else lo
            w.writerow([c["class"], c["name_vi"], lo, hi, kcal, match, describe(base), describe(high) if high else "",
                        note])
    print(OUT, len(classes), "lớp")


if __name__ == "__main__":
    main()
