"""Cắt đồ thị con đái tháo đường từ PrimeKG và ghép các yếu tố nguy cơ của DiaCare vào đó.

PrimeKG (Chandak, Huang & Zitnik 2023, Scientific Data; giấy phép CC0 1.0) tải từ Harvard Dataverse
doi:10.7910/DVN/IXA7BM: chỉ cần nodes.tab (8,9 MB) và edges.csv (386,6 MB).

Cách cắt:
1. Hạt giống: mọi nút bệnh có "diabet" trong tên trừ đái tháo nhạt (diabetes insipidus, bệnh khác hẳn),
   cộng các nút ứng với yếu tố nguy cơ của DiaCare (PRIMEKG_MAP).
2. Lấy hàng xóm 1 bước của hạt giống, rồi giữ mọi cạnh PrimeKG nối hai nút trong tập (đồ thị con cảm sinh).
3. Tuỳ chọn --hops 2: thêm hàng xóm bước 2 nhưng chỉ những nút có ít nhất --min-links cạnh vào tập bước 1,
   để đồ thị không phình ra cả PrimeKG.
4. Chia cạnh train/valid/test (80/10/10) theo cặp vô hướng, để hai chiều của cùng một cạnh không rơi
   vào hai phần khác nhau (rò rỉ đáp án).

    python tools/primekg_subgraph.py --primekg D:/Temp/primekg --out data/kg_rgcn
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Yếu tố nguy cơ DiaCare (kg.RISK_FACTORS) -> tên nút PrimeKG. Yếu tố không có nút tương ứng thì bỏ
# (tuổi, ít vận động, chế độ ăn, chủng tộc, tiền sử gia đình, gen: PrimeKG không mô hình hóa lối sống).
PRIMEKG_MAP = {
    "OBESITY": ["obesity disorder", "Overweight"],
    "HIGH_BP": ["hypertension"],
    "HIGH_CHOL": ["hyperlipidemia", "Hypercholesterolemia"],
    "HEART_DISEASE": ["coronary artery disease", "myocardial infarction"],
    "STROKE": ["stroke disorder"],
    "SMOKING": ["Tobacco Smoke Pollution"],
    "PREDIABETES": ["prediabetes syndrome"],
    "GESTATIONAL": ["gestational diabetes"],
    "PCOS": ["polycystic ovary syndrome"],
    "DEPRESSION": ["major depressive disorder"],
    "ACANTHOSIS": ["acanthosis nigricans (disease)"],
}
TARGETS = ["type 2 diabetes mellitus", "diabetes mellitus (disease)"]
# Lưu ý: disease_disease trong PrimeKG là quan hệ PHÂN CẤP danh mục bệnh (MONDO: cha -> con), không phải
# "liên quan nguy cơ". Vì vậy không hỏi RGCN "có cạnh disease_disease giữa béo phì và T2D không".
# Thay vào đó mỗi cặp (yếu tố, đích) có hai loại bằng chứng:
#   - trực tiếp trong PrimeKG: số gen/protein chung, số kiểu hình chung (tính ở đây, không cần học máy);
#   - độ gần trong không gian embedding RGCN (tính trong kg_rgcn.py).
# Tương tác thuốc-thuốc chiếm khoảng 80% cạnh quanh đái tháo đường mà không liên quan bài toán: bỏ mặc định.
DEFAULT_DROP = ("drug_drug",)


EVIDENCE_TARGET = "type 2 diabetes mellitus"
GENE_RELS = ("disease_protein", "phenotype_protein", "exposure_protein")


def write_evidence(path, mapping, by_name, name_of, all_edges, dm_nodes, neigh):
    """Tệp nhỏ cho kg.py: với mỗi yếu tố DiaCare, các gen mà PrimeKG nối với cả yếu tố đó lẫn T2D.

    Đây là bằng chứng tra cứu, cố định, không có học máy. Gen ví dụ xếp theo số bệnh đái tháo đường
    (trong 68 nút hạt giống) mà gen đó được nối tới, để gen liên quan đái tháo đường nhiều nhất đứng đầu.
    """
    t2d = by_name[EVIDENCE_TARGET]
    target_genes = neigh(t2d, "disease_protein")
    dp = all_edges[(all_edges.relation == "disease_protein") & all_edges.x_index.isin(dm_nodes)]
    dm_degree = dp.groupby("y_index").size().to_dict()
    factors = {}
    for fid, nodes_ in mapping.items():
        genes = set()
        for n in nodes_:
            for rel in GENE_RELS:
                genes |= neigh(n, rel)
        shared = genes & target_genes
        ranked = sorted(shared, key=lambda gi: (-dm_degree.get(gi, 0), name_of[gi]))
        factors[fid] = {"primekg_nodes": [name_of[n] for n in nodes_], "factor_genes": len(genes),
                        "shared_genes": len(shared), "genes": [name_of[gi] for gi in ranked]}
    doc = {"source": "PrimeKG v2.1 (Chandak, Huang & Zitnik 2023, Scientific Data), Harvard Dataverse "
                     "doi:10.7910/DVN/IXA7BM, CC0 1.0",
           "target": EVIDENCE_TARGET, "target_genes": len(target_genes),
           "relations": list(GENE_RELS),
           "note": "Gen được PrimeKG nối với cả yếu tố lẫn T2D: bằng chứng cơ chế sinh học dùng chung, "
                   "không phải mức nguy cơ hay quan hệ nhân quả.",
           "factors": factors}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"đã ghi bằng chứng gen chung: {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--primekg", default="D:/Temp/primekg")
    ap.add_argument("--out", default="data/kg_rgcn")
    ap.add_argument("--hops", type=int, default=1)
    ap.add_argument("--min-links", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--drop-rels", default=",".join(DEFAULT_DROP), help="quan hệ bỏ, phân cách bằng dấu phẩy")
    ap.add_argument("--evidence", default="",
                    help="ghi bằng chứng gen chung (yếu tố DiaCare, T2D) ra tệp JSON, ví dụ kb/graph/primekg_shared_genes.json")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    src = Path(args.primekg)

    nodes = pd.read_csv(src / "nodes.tab")
    all_edges = pd.read_csv(src / "edges.csv", usecols=["relation", "x_index", "y_index"])
    drop = {r for r in args.drop_rels.split(",") if r}
    edges = all_edges[~all_edges.relation.isin(drop)]
    name_of = dict(zip(nodes.node_index, nodes.node_name))
    type_of = dict(zip(nodes.node_index, nodes.node_type))
    by_name = {}
    for i, nm in zip(nodes.node_index, nodes.node_name):
        by_name.setdefault(nm, i)

    is_dm = nodes.node_name.str.contains("diabet", case=False) & ~nodes.node_name.str.contains(
        "insipidus", case=False) & (nodes.node_type == "disease")
    seeds = set(nodes.node_index[is_dm])
    mapping = {}
    for fid, names in PRIMEKG_MAP.items():
        found = [by_name[n] for n in names if n in by_name]
        missing = [n for n in names if n not in by_name]
        if missing:
            print(f"[warn] {fid}: không thấy {missing}")
        mapping[fid] = found
        seeds |= set(found)
    targets = [by_name[t] for t in TARGETS]

    x, y = edges.x_index.to_numpy(), edges.y_index.to_numpy()
    seed_arr = np.fromiter(seeds, dtype=np.int64)
    touch = np.isin(x, seed_arr) | np.isin(y, seed_arr)
    keep = set(seed_arr) | set(x[touch]) | set(y[touch])
    print(f"hạt giống {len(seeds)} nút; sau 1 bước: {len(keep)} nút")

    if args.hops >= 2:
        k1 = np.fromiter(keep, dtype=np.int64)
        in1x, in1y = np.isin(x, k1), np.isin(y, k1)
        border = np.concatenate([y[in1x & ~in1y], x[in1y & ~in1x]])
        cand, cnt = np.unique(border, return_counts=True)
        add = cand[cnt >= args.min_links]
        keep |= set(add)
        print(f"sau 2 bước (>= {args.min_links} cạnh vào tập 1 bước): {len(keep)} nút")

    karr = np.fromiter(keep, dtype=np.int64)
    m = np.isin(x, karr) & np.isin(y, karr)
    sub = edges[m].copy()
    # PrimeKG lưu mỗi cạnh vô hướng thành hai dòng: gộp về một cặp có thứ tự để chia train/test không rò rỉ.
    a, b = sub.x_index.to_numpy(), sub.y_index.to_numpy()
    sub["u"], sub["v"] = np.minimum(a, b), np.maximum(a, b)
    pairs = sub.drop_duplicates(["relation", "u", "v"])[["relation", "u", "v"]].reset_index(drop=True)
    rng = np.random.default_rng(args.seed)
    r = rng.random(len(pairs))
    pairs["split"] = np.where(r < 0.8, "train", np.where(r < 0.9, "valid", "test"))

    # Đánh lại chỉ số nút 0..N-1.
    used = np.unique(np.concatenate([pairs.u, pairs.v]))
    idx = {int(n): i for i, n in enumerate(used)}
    out_nodes = pd.DataFrame({"idx": range(len(used)), "primekg_index": used,
                              "name": [name_of[n] for n in used], "type": [type_of[n] for n in used]})
    # Hướng cạnh theo quy ước PrimeKG để quan hệ có nghĩa: ghi theo dòng gốc đầu tiên của cặp.
    first = sub.drop_duplicates(["relation", "u", "v"]).set_index(["relation", "u", "v"])
    heads, tails = [], []
    for rel, u, v in zip(pairs.relation, pairs.u, pairs.v):
        row = first.loc[(rel, u, v)]
        heads.append(idx[int(row.x_index)])
        tails.append(idx[int(row.y_index)])
    out_edges = pd.DataFrame({"head": heads, "rel": pairs.relation, "tail": tails, "split": pairs.split})

    # Truy vấn: mỗi nút yếu tố DiaCare -> mỗi nút đích, kèm bằng chứng trực tiếp từ TOÀN BỘ PrimeKG.
    # PrimeKG lưu cả hai chiều, nên chỉ cần lọc theo cột x. Lọc trước theo các nút cần để khỏi quét 8 triệu dòng nhiều lần.
    qnodes = np.fromiter({n for v in mapping.values() for n in v} | set(targets), dtype=np.int64)
    near = all_edges[np.isin(all_edges.x_index.to_numpy(), qnodes)]
    ax, ay, arel = near.x_index.to_numpy(), near.y_index.to_numpy(), near.relation.to_numpy()

    def neigh(n, rel):
        return set(ay[(ax == n) & (arel == rel)])

    def direct(a, b):
        return sorted(set(arel[(ax == a) & (ay == b)]))

    q = []
    for fid, found in mapping.items():
        for f in found:
            for t in targets:
                if f not in idx or t not in idx:
                    continue
                gf = neigh(f, "disease_protein") | neigh(f, "phenotype_protein") | neigh(f, "exposure_protein")
                # gf/gt là tập chỉ số nút gen trong PrimeKG.
                gt = neigh(t, "disease_protein")
                pf = neigh(f, "disease_phenotype_positive") | ({f} if type_of[f] == "effect/phenotype" else set())
                pt = neigh(t, "disease_phenotype_positive")
                q.append({"factor": fid, "factor_node": name_of[f], "factor_type": type_of[f],
                          "target": name_of[t], "head": idx[f], "tail": idx[t],
                          "direct_relations": "|".join(direct(f, t)),
                          "shared_genes": len(gf & gt), "factor_genes": len(gf), "target_genes": len(gt),
                          "shared_phenotypes": len(pf & pt)})
    out_q = pd.DataFrame(q)

    if args.evidence:
        write_evidence(args.evidence, mapping, by_name, name_of, all_edges, nodes.node_index[is_dm].to_numpy(), neigh)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    out_nodes.to_csv(out / "nodes.csv", index=False)
    out_edges.to_csv(out / "edges.csv", index=False)
    out_q.to_csv(out / "queries.csv", index=False)
    summary = {
        "source": "PrimeKG v2.1, Harvard Dataverse doi:10.7910/DVN/IXA7BM (CC0 1.0)",
        "hops": args.hops, "min_links": args.min_links, "dropped_relations": sorted(drop),
        "nodes": int(len(out_nodes)), "edges": int(len(out_edges)),
        "nodes_by_type": out_nodes.type.value_counts().to_dict(),
        "edges_by_relation": out_edges.rel.value_counts().to_dict(),
        "split": out_edges.split.value_counts().to_dict(),
        "diabetes_seed_diseases": int(is_dm.sum()),
        "diacare_mapping": {k: [name_of[i] for i in v] for k, v in mapping.items()},
        "queries": int(len(out_q)),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
