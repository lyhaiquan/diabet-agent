"""Gộp dữ liệu tiểu đường từ nhiều nguồn về cùng 21 chỉ số của BRFSS 2015 (lược đồ của Predictor).

Nguồn (tải sẵn vào ../diacare_datasets, xem LINK_DATASET.md ở đó):
- BRFSS 2015 (CDC, UCI id 891): bản đã làm sạch, giữ nguyên.
- BRFSS 2023 (CDC, LLCP2023.XPT): mã hoá lại từng biến theo đúng quy ước của bản 2015.
- NHANES 2013-2020 (CDC, có xét nghiệm): ánh xạ được 13/21 chỉ số; các chỉ số còn lại để trống (NaN).
UCI 529 (triệu chứng) và Pima (chỉ số lâm sàng) có bộ cột khác hẳn nên không gộp vào đây; xem
tools/train_aux_models.py.

Nhãn chung `Diabetes_binary`: 1 = được bác sĩ chẩn đoán đái tháo đường (tự khai); tiền ĐTĐ và ĐTĐ chỉ khi
mang thai = 0 (đúng như bản UCI 2015: 35.346 / 253.680 = 13,9%). NHANES có thêm nhãn xét nghiệm
`diabetes_lab` (tự khai, hoặc HbA1c >= 6,5%, hoặc đường huyết đói >= 126 mg/dL) chỉ để đánh giá;
không bao giờ là đặc trưng.

Ra: data/multisource/{brfss2015,brfss2023,nhanes}.parquet (gitignore) và
docs/results/multisource_marginals.json (so trung bình từng chỉ số giữa các nguồn để bắt lỗi mã hoá).

Chạy:  python tools/build_multisource.py [thư_mục_dữ_liệu]
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DIACARE_DATASETS")
            or ROOT.parent / "diacare_datasets")
OUT = ROOT / "data" / "multisource"
REPORT = ROOT / "docs" / "results" / "multisource_marginals.json"

FEATURES = ["HighBP", "HighChol", "CholCheck", "BMI", "Smoker", "Stroke", "HeartDiseaseorAttack", "PhysActivity",
            "Fruits", "Veggies", "HvyAlcoholConsump", "AnyHealthcare", "NoDocbcCost", "GenHlth", "MentHlth",
            "PhysHlth", "DiffWalk", "Sex", "Age", "Education", "Income"]
LABEL = "Diabetes_binary"


def yes_no(s, yes=1, no=2):
    """Mã khảo sát 1 = có, 2 = không (mặc định) -> 1/0; mọi mã khác (7, 9, trống) -> NaN."""
    return s.map({yes: 1.0, no: 0.0})


# ---------- BRFSS 2015 ----------

def brfss2015():
    df = pd.read_csv(DATA / "brfss" / "cdc_diabetes_health_indicators.csv")
    out = df[FEATURES + [LABEL]].astype("float32")
    out["source"] = "brfss2015"
    return out


# ---------- BRFSS 2023 ----------

BRFSS23_COLS = ["DIABETE4", "_RFHYPE6", "TOLDHI3", "_CHOLCH3", "_BMI5", "SMOKE100", "CVDSTRK3", "_MICHD",
                "_TOTINDA", "_RFDRHV8", "_HLTHPL1", "MEDCOST1", "GENHLTH", "MENTHLTH", "PHYSHLTH", "DIFFWALK",
                "SEXVAR", "_AGEG5YR", "EDUCA", "INCOME3"]


def _days(s):
    """MENTHLTH/PHYSHLTH: 1-30 ngày; 88 = không ngày nào -> 0; 77/99 -> NaN."""
    s = s.where(~s.isin([77, 99]))
    return s.where(s != 88, 0.0).where(lambda x: x <= 30)


def brfss2023():
    cache = OUT / "brfss2023_raw.parquet"
    if cache.exists():
        raw = pd.read_parquet(cache)
    else:   # tệp 1,2 GB: đọc theo khối, chỉ giữ cột cần
        parts = [c[BRFSS23_COLS] for c in pd.read_sas(DATA / "brfss2023" / "LLCP2023.XPT", format="xport",
                                                       chunksize=100000)]
        raw = pd.concat(parts, ignore_index=True)
        raw.to_parquet(cache)
    o = pd.DataFrame(index=raw.index)
    o["HighBP"] = raw["_RFHYPE6"].map({1: 0.0, 2: 1.0})          # 2 = có tăng huyết áp
    o["HighChol"] = yes_no(raw["TOLDHI3"])
    o["CholCheck"] = raw["_CHOLCH3"].map({1: 1.0, 2: 0.0, 3: 0.0})  # 1 = kiểm tra trong 5 năm
    o["BMI"] = (raw["_BMI5"] / 100).round()
    o["Smoker"] = yes_no(raw["SMOKE100"])
    o["Stroke"] = yes_no(raw["CVDSTRK3"])
    o["HeartDiseaseorAttack"] = yes_no(raw["_MICHD"])
    o["PhysActivity"] = yes_no(raw["_TOTINDA"])
    o["Fruits"] = np.nan                                          # năm 2023 không hỏi rau quả
    o["Veggies"] = np.nan
    o["HvyAlcoholConsump"] = raw["_RFDRHV8"].map({1: 0.0, 2: 1.0})
    o["AnyHealthcare"] = yes_no(raw["_HLTHPL1"])
    o["NoDocbcCost"] = yes_no(raw["MEDCOST1"])
    o["GenHlth"] = raw["GENHLTH"].where(raw["GENHLTH"].between(1, 5))
    o["MentHlth"] = _days(raw["MENTHLTH"])
    o["PhysHlth"] = _days(raw["PHYSHLTH"])
    o["DiffWalk"] = yes_no(raw["DIFFWALK"])
    o["Sex"] = raw["SEXVAR"].map({1: 1.0, 2: 0.0})                # như bản 2015: 1 = nam
    o["Age"] = raw["_AGEG5YR"].where(raw["_AGEG5YR"].between(1, 13))
    o["Education"] = raw["EDUCA"].where(raw["EDUCA"].between(1, 6))
    inc = raw["INCOME3"].where(raw["INCOME3"].between(1, 11))
    o["Income"] = inc.clip(upper=8)                               # 2015: 8 = từ 75 nghìn USD trở lên
    o[LABEL] = raw["DIABETE4"].map({1: 1.0, 2: 0.0, 3: 0.0, 4: 0.0})
    # Như bản UCI 2015: bỏ dòng thiếu bất kỳ chỉ số nào (trừ rau quả, năm 2023 không hỏi)
    keep = [c for c in FEATURES if c not in ("Fruits", "Veggies")] + [LABEL]
    o = o.dropna(subset=keep).astype("float32")
    o["source"] = "brfss2023"
    return o, len(raw)


# ---------- NHANES ----------

CYCLES = (("P_", "", "2017-2020"), ("", "_I", "2015-2016"), ("", "_H", "2013-2014"))


def _age_group(age):
    """Tuổi thật -> nhóm 5 năm của BRFSS: 18-24 = 1, 25-29 = 2, ..., 75-79 = 12, 80+ = 13."""
    return np.where(age < 25, 1, np.minimum(13, (age - 25) // 5 + 2)).astype("float32")


def nhanes():
    frames = []
    for pre, suf, name in CYCLES:
        rd = lambda c: pd.read_sas(DATA / "nhanes" / f"{pre}{c}{suf}.xpt")  # noqa: E731
        d = rd("DEMO")[["SEQN", "RIAGENDR", "RIDAGEYR", "DMDEDUC2", "RIDEXPRG"]]
        for comp, cols in (("DIQ", ["DIQ010"]), ("GHB", ["LBXGH"]), ("GLU", ["LBXGLU"]), ("BMX", ["BMXBMI"]),
                           ("BPQ", ["BPQ020", "BPQ080", "BPQ060", "BPQ070"]), ("SMQ", ["SMQ020"]),
                           ("PAQ", ["PAQ650", "PAQ665"]), ("MCQ", ["MCQ160C", "MCQ160E", "MCQ160F"])):
            d = d.merge(rd(comp)[["SEQN"] + cols], on="SEQN", how="left")
        d = d[(d["RIDAGEYR"] >= 18) & (d["RIDEXPRG"] != 1)]     # người lớn, bỏ người đang mang thai
        o = pd.DataFrame(index=d.index)
        o["HighBP"] = yes_no(d["BPQ020"])
        o["HighChol"] = yes_no(d["BPQ080"])
        # BPQ070: lần kiểm tra mỡ máu gần nhất (1 <1 năm, 2 1-2 năm, 3 2-5 năm, 4 >5 năm); chưa từng (BPQ060=2) -> 0
        o["CholCheck"] = d["BPQ070"].map({1: 1.0, 2: 1.0, 3: 1.0, 4: 0.0})
        o.loc[d["BPQ060"] == 2, "CholCheck"] = 0.0
        o["BMI"] = d["BMXBMI"].round()
        o["Smoker"] = yes_no(d["SMQ020"])
        o["Stroke"] = yes_no(d["MCQ160F"])
        heart = (d["MCQ160C"] == 1) | (d["MCQ160E"] == 1)
        known = d["MCQ160C"].isin([1, 2]) & d["MCQ160E"].isin([1, 2])
        o["HeartDiseaseorAttack"] = np.where(heart, 1.0, np.where(known, 0.0, np.nan))
        # Gần nhất với "có vận động thể lực trong 30 ngày qua": có hoạt động giải trí mạnh hoặc vừa
        act = (d["PAQ650"] == 1) | (d["PAQ665"] == 1)
        known = d["PAQ650"].isin([1, 2]) & d["PAQ665"].isin([1, 2])
        o["PhysActivity"] = np.where(act, 1.0, np.where(known, 0.0, np.nan))
        for c in ("Fruits", "Veggies", "HvyAlcoholConsump", "AnyHealthcare", "NoDocbcCost", "GenHlth",
                  "MentHlth", "PhysHlth", "DiffWalk", "Income"):
            o[c] = np.nan                                          # không có trong 9 tệp đã tải
        o["Sex"] = d["RIAGENDR"].map({1: 1.0, 2: 0.0})
        o["Age"] = _age_group(d["RIDAGEYR"])
        o["Education"] = d["DMDEDUC2"].map({1: 2.0, 2: 3.0, 3: 4.0, 4: 5.0, 5: 6.0})
        o[LABEL] = d["DIQ010"].map({1: 1.0, 2: 0.0, 3: 0.0})       # 3 = giáp ranh -> 0, như BRFSS
        lab = (d["LBXGH"] >= 6.5) | (d["LBXGLU"] >= 126)
        o["diabetes_lab"] = np.where((o[LABEL] == 1) | lab, 1.0, np.where(d["LBXGH"].notna(), 0.0, np.nan))
        o["hba1c"], o["fpg"] = d["LBXGH"], d["LBXGLU"]
        o["cycle"] = name
        frames.append(o)
    o = pd.concat(frames, ignore_index=True)
    o = o.dropna(subset=[LABEL, "BMI", "Age", "Sex"])
    o[FEATURES + [LABEL, "diabetes_lab", "hba1c", "fpg"]] = o[FEATURES + [LABEL, "diabetes_lab", "hba1c",
                                                                          "fpg"]].astype("float32")
    o["source"] = "nhanes"
    return o


def marginals(frames):
    rep = {}
    for name, df in frames.items():
        rep[name] = {"rows": int(len(df)), "positive_rate": round(float(df[LABEL].mean()), 4),
                     "features": {c: (None if df[c].isna().all() else round(float(df[c].mean()), 3))
                                  for c in FEATURES},
                     "missing_share": {c: round(float(df[c].isna().mean()), 3) for c in FEATURES
                                       if df[c].isna().any()}}
        if "diabetes_lab" in df:
            lab = df["diabetes_lab"].dropna()
            rep[name]["lab_confirmed_rate"] = round(float(lab.mean()), 4)
            rep[name]["undiagnosed_share_of_lab_positive"] = round(
                float(((df["diabetes_lab"] == 1) & (df[LABEL] == 0)).sum() / max(1, (df["diabetes_lab"] == 1).sum())), 3)
    return rep


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    b15 = brfss2015()
    b23, raw23 = brfss2023()
    nh = nhanes()
    frames = {"brfss2015": b15, "brfss2023": b23, "nhanes": nh}
    for name, df in frames.items():
        df.to_parquet(OUT / f"{name}.parquet")
    rep = marginals(frames)
    rep["brfss2023"]["raw_rows"] = int(raw23)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'chỉ số':<22}" + "".join(f"{n:>12}" for n in frames))
    for c in FEATURES + ["positive_rate", "rows"]:
        vals = [rep[n]["features"].get(c) if c in FEATURES else rep[n][c] for n in frames]
        print(f"{c:<22}" + "".join(f"{'-' if v is None else v:>12}" for v in vals))
    print("NHANES nhãn xét nghiệm:", rep["nhanes"]["lab_confirmed_rate"],
          "| tỉ lệ chưa được chẩn đoán trong số dương theo xét nghiệm:", rep["nhanes"]["undiagnosed_share_of_lab_positive"])


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    main()
