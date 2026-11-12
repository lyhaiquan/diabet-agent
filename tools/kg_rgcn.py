"""Huấn luyện RGCN dự đoán cạnh trên đồ thị con đái tháo đường (PrimeKG + DiaCare).

Chạy được trên CPU (máy cá nhân) lẫn GPU (Kaggle) chỉ với PyTorch, không cần PyTorch Geometric.

Đầu vào: thư mục do tools/primekg_subgraph.py tạo ra (nodes.csv, edges.csv, queries.csv).
Đầu ra:  metrics.json (MRR, Hits@k trên cạnh kiểm tra) và predictions.json (điểm cho các cặp
         yếu tố nguy cơ DiaCare -> bệnh đái tháo đường mà đồ thị chưa có cạnh).

Phương pháp theo CS224W tr. 51-54 (bản PDF):
- Bộ mã hóa RGCN: mỗi loại quan hệ một ma trận, dùng phân rã cơ sở (basis) để bớt tham số.
- Bộ giải mã DistMult: điểm(h, r, t) = <z_h, w_r, z_t>.
- Tách cạnh thành 3 phần: train (vừa truyền thông điệp vừa giám sát), valid, test.
- Mẫu âm: thay đuôi bằng nút ngẫu nhiên CÙNG LOẠI với đuôi thật.
- Đánh giá: xếp hạng đuôi thật giữa mọi nút cùng loại (lọc bỏ các đuôi đúng khác), lấy MRR và Hits@1/3/10.

    python tools/kg_rgcn.py --data data/kg_rgcn --out data/kg_rgcn/run --epochs 300
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn


# ---------------- dữ liệu ----------------

def load_graph(data_dir):
    import pandas as pd
    d = Path(data_dir)
    nodes = pd.read_csv(d / "nodes.csv")          # idx, node_id, name, type
    edges = pd.read_csv(d / "edges.csv")          # head, rel, tail, split  (head/tail là idx)
    rels = sorted(edges["rel"].unique())
    rel_id = {r: i for i, r in enumerate(rels)}
    types = sorted(nodes["type"].unique())
    type_id = {t: i for i, t in enumerate(types)}
    trip = np.stack([edges["head"].to_numpy(), edges["rel"].map(rel_id).to_numpy(),
                     edges["tail"].to_numpy()], axis=1).astype(np.int64)
    split = edges["split"].to_numpy()
    node_type = nodes["type"].map(type_id).to_numpy().astype(np.int64)
    queries = pd.read_csv(d / "queries.csv") if (d / "queries.csv").exists() else None
    return dict(nodes=nodes, rels=rels, rel_id=rel_id, types=types, node_type=node_type,
                train=trip[split == "train"], valid=trip[split == "valid"], test=trip[split == "test"],
                queries=queries)


def message_edges(train, n_rel):
    """Cạnh truyền thông điệp: mỗi cạnh train thêm chiều ngược (quan hệ r + n_rel), cộng vòng tự thân xử lý riêng."""
    h, r, t = train[:, 0], train[:, 1], train[:, 2]
    src = np.concatenate([h, t])
    dst = np.concatenate([t, h])
    rel = np.concatenate([r, r + n_rel])
    return torch.from_numpy(src), torch.from_numpy(dst), torch.from_numpy(rel)


# ---------------- mô hình ----------------

class RGCNLayer(nn.Module):
    """h_i' = W_0 h_i + sum_r sum_{j in N_r(i)} (1/c_{i,r}) W_r h_j,   W_r = sum_b a_{rb} V_b."""

    def __init__(self, dim_in, dim_out, n_rel, n_bases):
        super().__init__()
        self.n_rel = n_rel
        self.bases = nn.Parameter(torch.empty(n_bases, dim_in, dim_out))
        self.coef = nn.Parameter(torch.empty(n_rel, n_bases))
        self.self_loop = nn.Linear(dim_in, dim_out, bias=True)
        nn.init.xavier_uniform_(self.bases)
        nn.init.xavier_uniform_(self.coef)

    def forward(self, x, src, dst, rel, norm):
        weight = torch.einsum("rb,bio->rio", self.coef, self.bases)      # (R, in, out)
        # Nhóm theo quan hệ để không phải tạo tensor (E, in, out).
        out = self.self_loop(x)
        msg = torch.zeros_like(out)
        for r in range(self.n_rel):
            m = rel == r
            if not m.any():
                continue
            s, d = src[m], dst[m]
            msg.index_add_(0, d, (x[s] @ weight[r]) * norm[m].unsqueeze(1))
        return out + msg


class RGCNLinkPredictor(nn.Module):
    def __init__(self, n_nodes, n_rel, dim=64, n_bases=8, n_layers=2, dropout=0.2):
        super().__init__()
        self.emb = nn.Embedding(n_nodes, dim)
        nn.init.xavier_uniform_(self.emb.weight)
        self.layers = nn.ModuleList(RGCNLayer(dim, dim, 2 * n_rel, n_bases) for _ in range(n_layers))
        self.rel = nn.Parameter(torch.empty(n_rel, dim))                # DistMult
        nn.init.xavier_uniform_(self.rel)
        self.drop = nn.Dropout(dropout)

    def encode(self, src, dst, rel, norm):
        x = self.emb.weight
        for i, layer in enumerate(self.layers):
            x = layer(x, src, dst, rel, norm)
            if i < len(self.layers) - 1:
                x = self.drop(torch.relu(x))
        return x

    def score(self, z, h, r, t):
        return (z[h] * self.rel[r] * z[t]).sum(-1)


def edge_norm(dst, rel, n_nodes, n_rel2):
    """1/c_{i,r}: c là số hàng xóm của nút đích i theo quan hệ r."""
    key = dst * n_rel2 + rel
    _, inv, cnt = torch.unique(key, return_inverse=True, return_counts=True)
    return 1.0 / cnt[inv].float()


# ---------------- huấn luyện & đánh giá ----------------

def sample_negatives(trip, node_type, by_type, k, gen):
    """Mỗi cạnh dương sinh k cạnh âm bằng cách thay đuôi bằng nút cùng loại."""
    t_types = node_type[trip[:, 2]]
    neg_t = np.empty((len(trip), k), dtype=np.int64)
    for ty in np.unique(t_types):
        rows = np.nonzero(t_types == ty)[0]
        pool = by_type[ty]
        neg_t[rows] = pool[gen.integers(0, len(pool), size=(len(rows), k))]
    neg = np.repeat(trip, k, axis=0)
    neg[:, 2] = neg_t.reshape(-1)
    return neg


@torch.no_grad()
def rank_eval(model, z, trip, node_type, by_type, known, device, max_n=2000):
    """Xếp hạng có lọc (filtered): đuôi thật so với mọi nút cùng loại, bỏ các đuôi đúng khác."""
    if len(trip) > max_n:
        trip = trip[np.random.default_rng(0).choice(len(trip), max_n, replace=False)]
    ranks = []
    for h, r, t in trip:
        cand = by_type[node_type[t]]
        c = torch.from_numpy(cand).to(device)
        s = model.score(z, torch.full_like(c, int(h)), torch.full_like(c, int(r)), c)
        bad = np.array([(int(h), int(r), int(x)) in known and x != t for x in cand])
        s[torch.from_numpy(bad).to(device)] = -math.inf
        true_s = s[int(np.nonzero(cand == t)[0][0])]
        ranks.append(int((s > true_s).sum().item()) + 1)
    ranks = np.array(ranks, dtype=np.float64)
    return {"n": int(len(ranks)), "mrr": float((1 / ranks).mean()),
            "hits@1": float((ranks <= 1).mean()), "hits@3": float((ranks <= 3).mean()),
            "hits@10": float((ranks <= 10).mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/kg_rgcn")
    ap.add_argument("--out", default="data/kg_rgcn/run")
    ap.add_argument("--epochs", type=int, default=300)
    ap.add_argument("--dim", type=int, default=64)
    ap.add_argument("--bases", type=int, default=8)
    ap.add_argument("--layers", type=int, default=2)
    ap.add_argument("--neg", type=int, default=8)
    ap.add_argument("--lr", type=float, default=0.01)
    ap.add_argument("--batch", type=int, default=20000, help="số cạnh giám sát mỗi bước")
    ap.add_argument("--eval-every", type=int, default=25)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    torch.manual_seed(args.seed)
    gen = np.random.default_rng(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    g = load_graph(args.data)
    n_nodes, n_rel = len(g["nodes"]), len(g["rels"])
    node_type = g["node_type"]
    by_type = {ty: np.nonzero(node_type == ty)[0] for ty in np.unique(node_type)}
    known = set(map(tuple, np.concatenate([g["train"], g["valid"], g["test"]]).tolist()))
    print(f"[rgcn] {device} · {n_nodes} nút · {n_rel} quan hệ · train {len(g['train'])} "
          f"valid {len(g['valid'])} test {len(g['test'])}", flush=True)

    src, dst, rel = (x.to(device) for x in message_edges(g["train"], n_rel))
    norm = edge_norm(dst, rel, n_nodes, 2 * n_rel)
    model = RGCNLinkPredictor(n_nodes, n_rel, args.dim, args.bases, args.layers).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-5)
    loss_fn = nn.BCEWithLogitsLoss()
    best, best_state, history = -1.0, None, []
    t0 = time.time()
    for ep in range(1, args.epochs + 1):
        model.train()
        pos = g["train"][gen.choice(len(g["train"]), min(args.batch, len(g["train"])), replace=False)]
        neg = sample_negatives(pos, node_type, by_type, args.neg, gen)
        both = torch.from_numpy(np.concatenate([pos, neg])).to(device)
        y = torch.cat([torch.ones(len(pos)), torch.zeros(len(neg))]).to(device)
        z = model.encode(src, dst, rel, norm)
        logits = model.score(z, both[:, 0], both[:, 1], both[:, 2])
        loss = loss_fn(logits, y) + 1e-3 * (z.pow(2).mean() + model.rel.pow(2).mean())
        opt.zero_grad()
        loss.backward()
        opt.step()
        if ep % args.eval_every == 0 or ep == args.epochs:
            model.eval()
            z = model.encode(src, dst, rel, norm)
            v = rank_eval(model, z, g["valid"], node_type, by_type, known, device, max_n=1000)
            history.append({"epoch": ep, "loss": loss.item(), **v})
            print(f"[rgcn] ep {ep:4d} loss {loss.item():.4f} valid MRR {v['mrr']:.3f} "
                  f"H@10 {v['hits@10']:.3f} ({time.time() - t0:.0f}s)", flush=True)
            if v["mrr"] > best:
                best, best_state = v["mrr"], {k: x.detach().clone() for k, x in model.state_dict().items()}

    model.load_state_dict(best_state)
    model.eval()
    z = model.encode(src, dst, rel, norm)
    test = rank_eval(model, z, g["test"], node_type, by_type, known, device)
    per_rel = {}
    for r_name, r_idx in g["rel_id"].items():
        sub = g["test"][g["test"][:, 1] == r_idx]
        if len(sub) >= 5:
            per_rel[r_name] = rank_eval(model, z, sub, node_type, by_type, known, device, max_n=500)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    metrics = {"device": str(device), "nodes": n_nodes, "relations": n_rel,
               "edges": {k: int(len(g[k])) for k in ("train", "valid", "test")},
               "args": vars(args), "best_valid_mrr": best, "test": test, "test_by_relation": per_rel,
               "history": history, "seconds": round(time.time() - t0, 1)}
    (out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[rgcn] TEST MRR {test['mrr']:.3f} H@1 {test['hits@1']:.3f} H@10 {test['hits@10']:.3f}", flush=True)

    # Cặp truy vấn (yếu tố DiaCare, bệnh đái tháo đường): độ gần cosin trong không gian embedding,
    # quy ra phân vị so với mọi nút CÙNG LOẠI với yếu tố. Phân vị 0,98 nghĩa là trong các bệnh (hoặc kiểu hình)
    # của đồ thị, yếu tố này nằm gần đích hơn 98% số còn lại. Đây là độ liên quan mô hình học được, không phải
    # nguy cơ hay nhân quả.
    if g["queries"] is not None and len(g["queries"]):
        q = g["queries"].copy()
        with torch.no_grad():
            zn = torch.nn.functional.normalize(z, dim=1)
            sims, pcts = [], []
            for f, t in zip(q["head"], q["tail"]):
                pool = torch.from_numpy(by_type[node_type[f]]).to(device)
                all_s = zn[pool] @ zn[int(t)]
                s = float(zn[int(f)] @ zn[int(t)])
                sims.append(round(s, 4))
                pcts.append(round(float((all_s < s).float().mean()), 3))
        q["embedding_cosine"] = sims
        q["embedding_percentile"] = pcts
        q = q.sort_values(["target", "embedding_percentile"], ascending=[True, False])
        (out / "predictions.json").write_text(
            q.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
        print(q.drop(columns=["head", "tail"]).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
