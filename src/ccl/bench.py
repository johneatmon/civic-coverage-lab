"""City-parameterised siting benchmark: MCLP vs persistent homology vs trivial baselines.

The question is whether the topological gap-finding this project started from is any use
for the decision it is supposed to inform -- where the next branch goes. Every strategy
draws from the same candidate grid and is scored the same way, and `worst_point` is the
control: place at the worst-served inhabited cell, no topology anywhere.
"""

import numpy as np
from scipy import ndimage
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from ccl.build import load
from ccl.cities import PROFILES, get
from ccl.elevation import edge_seconds
from ccl.persistence import h1_diagram

STRIDE = 3
CONN4 = ndimage.generate_binary_structure(2, 1)


def setup(city_key: str, stride: int = STRIDE) -> dict:
    d = load(city_key)
    csr = csr_matrix((d["csr_data"], d["csr_indices"], d["csr_indptr"]),
                     shape=tuple(d["csr_shape"]))
    cand = np.zeros_like(d["inhabited"])
    cand[::stride, ::stride] = True
    cand &= d["inhabited"]
    rc = np.argwhere(cand)
    # Rebuild the adult travel-time matrix. edge_grade was stored in the COO ordering of
    # this same CSR, so the two line up element-for-element.
    adult = PROFILES[0]
    coo = csr.tocoo()
    secs = edge_seconds(coo.data, d["edge_grade"], adult.speed_mps, adult.max_grade)
    keep = np.isfinite(secs)
    tcsr = csr_matrix((secs[keep], (coo.row[keep], coo.col[keep])), shape=csr.shape)
    return {
        "d": d, "csr": csr, "tcsr": tcsr.T.tocsr(), "cand_rc": rc,
        "cand_nodes": np.array([d["cell_node"][r, c] for r, c in rc], dtype=np.int64),
        "city": get(city_key),
    }


def field_from(s: dict, nodes) -> np.ndarray:
    """Adult travel time in seconds, person -> nearest facility (graph already transposed)."""
    d = s["d"]
    adult = PROFILES[0]
    t = dijkstra(s["tcsr"], indices=np.unique(nodes), min_only=True)[d["cell_node"]]
    return np.where(d["land"], t + d["snap"] / adult.speed_mps, np.inf)


def masked(s: dict, f: np.ndarray) -> np.ndarray:
    return np.where(s["d"]["land"], f, np.inf)


def snap_candidate(s: dict, rc, exclude: set) -> int:
    """Snap to the candidate grid by NETWORK distance -- raster adjacency can be
    kilometres away on foot across a canal, which strands the strategy on one cell."""
    dn = dijkstra(s["csr"], indices=[int(s["d"]["cell_node"][rc[0], rc[1]])], min_only=True)  # noqa: E501
    dc = dn[s["cand_nodes"]].copy()
    if exclude:
        dc[list(exclude)] = np.inf
    if np.isfinite(dc).any():
        return int(np.argmin(dc))
    m = (np.abs(s["cand_rc"][:, 0] - rc[0]) + np.abs(s["cand_rc"][:, 1] - rc[1])).astype(float)
    if exclude:
        m[list(exclude)] = np.inf
    return int(np.argmin(m))


def coverage_matrix(s: dict, standard: float, batch: int = 120) -> np.ndarray:
    d = s["d"]
    n = len(s["cand_nodes"])
    out = np.zeros((n, d["cell_node"].size), dtype=bool)
    for i in range(0, n, batch):
        chunk = s["cand_nodes"][i:i + batch]
        dn = dijkstra(s["tcsr"].T.tocsr(), indices=chunk, limit=standard, min_only=False)
        for j in range(len(chunk)):
            f = dn[j][d["cell_node"]] + d["snap"] / PROFILES[0].speed_mps
            out[i + j] = ((f <= standard) & d["land"]).ravel()
    return out


# --------------------------------------------------------------- strategies


def mclp_greedy(s: dict, k: int, standard: float, cov: np.ndarray) -> list:
    d = s["d"]
    base = field_from(s, d["fac_nodes"])
    done = ((base <= standard) & d["inhabited"]).ravel()
    pop = np.where(d["inhabited"].ravel(), d["population"].ravel(), 0.0)
    picks: list[int] = []
    for _ in range(k):
        gain = (cov & ~done) @ pop
        if picks:
            gain[picks] = -1
        b = int(np.argmax(gain))
        picks.append(b)
        done = done | cov[b]
    return picks


def worst_point(s: dict, k: int, standard: float) -> list:
    d = s["d"]
    nodes = list(d["fac_nodes"])
    picks: list[int] = []
    for _ in range(k):
        f = np.where(d["inhabited"], field_from(s, np.array(nodes)), -np.inf)
        rc = np.unravel_index(np.argmax(f), f.shape)
        picks.append(snap_candidate(s, rc, set(picks)))
        nodes.append(int(s["cand_nodes"][picks[-1]]))
    return picks


def ph_strategy(s: dict, k: int, standard: float, mode: str) -> list:
    """mode='persistence': death cells of the most persistent H1 classes.
    mode='population': worst-served point of the highest-population pocket. Both adaptive."""
    d = s["d"]
    nodes = list(d["fac_nodes"])
    picks: list[int] = []
    while len(picks) < k:
        f = field_from(s, np.array(nodes))
        if mode == "persistence":
            _, cells = h1_diagram(masked(s, f))
            targets = [tuple(c) for c in cells]
        else:
            lab, n = ndimage.label((f > standard) & d["land"], structure=CONN4)
            scored = []
            for i in range(1, n + 1):
                reg = lab == i
                scored.append((d["population"][reg].sum(), reg))
            scored.sort(key=lambda x: -x[0])
            targets = []
            for _, reg in scored[:6]:
                m = np.where(reg, f, -np.inf)
                targets.append(np.unravel_index(np.argmax(m), m.shape))
        if not targets:
            break
        placed = False
        for t in targets:
            c = snap_candidate(s, t, set(picks))
            if c not in picks:
                picks.append(c)
                nodes.append(int(s["cand_nodes"][c]))
                placed = True
                break
        if not placed:
            break
    return picks


def random_picks(s: dict, k: int, seed: int) -> list:
    return list(np.random.default_rng(seed).choice(len(s["cand_nodes"]), k, replace=False))


# --------------------------------------------------------------- scoring


def score(s: dict, picks: list, standard: float) -> dict:
    d = s["d"]
    f = field_from(s, list(d["fac_nodes"]) + [int(s["cand_nodes"][p]) for p in picks])
    inh = d["inhabited"] & np.isfinite(f)
    dist, w = f[inh], d["population"][inh]
    o = np.argsort(dist)
    dist, w = dist[o], w[o]
    cw = np.cumsum(w) / w.sum()
    within = f <= standard
    return {
        "covered": float(w[dist <= standard].sum()),
        "nocar_hh": float(d["no_vehicle_hh"][inh & within].sum()),
        "older": float(d["pop_65plus"][inh & within].sum()),
        "worst": float(dist.max()),
        "p95": float(dist[np.searchsorted(cw, 0.95)]),
    }


def results(city_key: str, k: int = 8, minutes: int = 15) -> dict:
    standard = minutes * 60.0
    s = setup(city_key)
    cov = coverage_matrix(s, standard)

    strategies = {
        "MCLP greedy": mclp_greedy(s, k, standard, cov),
        "worst-point (no topology)": worst_point(s, k, standard),
        "PH by persistence": ph_strategy(s, k, standard, "persistence"),
        "PH by population": ph_strategy(s, k, standard, "population"),
    }
    base = score(s, [], standard)
    rows = {n: score(s, p, standard) for n, p in strategies.items()}
    rnd = [score(s, random_picks(s, k, sd), standard) for sd in range(5)]
    rows["random (mean of 5)"] = {kk: float(np.mean([r[kk] for r in rnd])) for kk in base}
    return {"s": s, "base": base, "rows": rows, "picks": strategies, "cov": cov,
            "standard": standard, "minutes": minutes, "k": k}


def run(city_key: str, k: int = 8, minutes: int = 15) -> dict:
    R = results(city_key, k, minutes)
    s, base, rows, standard = R["s"], R["base"], R["rows"], R["standard"]
    print(f"\n{'=' * 90}")
    print(f"{s['city'].place.upper()} — siting {k} new branches, "
          f"{minutes} min adult standard (slope-aware travel time)")
    print(f"existing: {len(s['d']['fac_nodes'])} branches · "
          f"candidates: {len(s['cand_nodes'])} sites")
    print(f"{'=' * 90}")
    print(f"{'strategy':30s}{'+covered':>12s}{'+car-free HH':>14s}"
          f"{'+65plus':>11s}{'worst walk':>13s}{'p95':>10s}")
    print("-" * 90)
    for n, r in rows.items():
        print(f"{n:30s}{r['covered'] - base['covered']:>+12,.0f}"
              f"{r['nocar_hh'] - base['nocar_hh']:>+14,.0f}"
              f"{r['older'] - base['older']:>+11,.0f}"
              f"{(r['worst'] - base['worst']) / 60:>+11,.1f}m"
              f"{(r['p95'] - base['p95']) / 60:>+8,.1f}m")
    best = max(rows.items(), key=lambda kv: kv[1]["covered"])
    print(f"\nbaseline covered: {base['covered']:,.0f} of "
          f"{s['d']['population'][s['d']['inhabited']].sum():,.0f} "
          f"({100 * base['covered'] / s['d']['population'][s['d']['inhabited']].sum():.1f}%)")
    print(f"best on coverage: {best[0]}")
    for n, r in sorted(rows.items(), key=lambda kv: -kv[1]["covered"]):
        g = r["covered"] - base["covered"]
        bg = best[1]["covered"] - base["covered"]
        print(f"  {n:30s} +{g:>8,.0f}  ({100 * g / bg:5.1f}% of best)")
    return R


if __name__ == "__main__":
    import sys

    for c in sys.argv[1:] or ["seattle", "tacoma"]:
        run(c)
