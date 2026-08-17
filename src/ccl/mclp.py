"""Does persistent homology beat maximal-covering location for siting new libraries?

The decision this benchmarks: "where should Seattle put the next k branches?"

Strategies all choose from the same candidate grid and are scored the same way -- extra
population brought within the service standard. The one that matters most is
`worst_point`: it places at the single worst-served inhabited cell, recomputing each
round, and uses no topology whatsoever. If persistent homology cannot beat that, the
topology is decoration.
"""

import time
from pathlib import Path

import numpy as np
from scipy.sparse.csgraph import dijkstra

from ccl.graph import load
from ccl.persistence import analyse, base_mask
from ccl.rank import SERVICE_STANDARD_M, pockets

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

STRIDE = 3  # candidate siting grid: every 3rd cell = 450 m spacing
K = 8  # new facilities to site


def setup(resource: str = "libraries") -> dict:
    import geopandas as gpd
    from scipy.spatial import cKDTree

    g = load()
    d = np.load(DATA / f"fields_{resource}.npz")
    dem = np.load(DATA / f"demand_{resource}.npz")
    snap, cell_node = d["snap"], g["cell_node"]

    land = base_mask(d, ~dem["water"]) & np.isfinite(d["network"])
    inhabited = land & (dem["population_density"] >= 100)

    fac = gpd.read_file(DATA / f"{resource}.geojson").to_crs("EPSG:32610")
    _, fac_nodes = cKDTree(g["node_xy"]).query(
        np.column_stack([fac.geometry.x, fac.geometry.y])
    )

    cand = np.zeros_like(inhabited)
    cand[::STRIDE, ::STRIDE] = True
    cand &= inhabited
    cand_rc = np.argwhere(cand)
    cand_nodes = cell_node[cand[:, :]][:0]  # placeholder, filled below
    cand_nodes = np.array([cell_node[r, c] for r, c in cand_rc], dtype=np.int64)

    return {
        "csr": g["csr"], "cell_node": cell_node, "snap": snap,
        "pop": dem["population"], "land": land, "inhabited": inhabited,
        "fac_nodes": np.unique(fac_nodes), "cand_rc": cand_rc, "cand_nodes": cand_nodes,
        "xs": g["xs"], "ys": g["ys"], "resource": resource, "water": dem["water"],
    }


def field_from(s: dict, nodes: np.ndarray) -> np.ndarray:
    """Nearest-facility distance field for an arbitrary facility node set."""
    dn = dijkstra(s["csr"], indices=np.unique(nodes), min_only=True)
    f = dn[s["cell_node"]] + s["snap"]
    return np.where(s["land"], f, np.inf)


def covered_pop(s: dict, field: np.ndarray, standard: float) -> float:
    return float(s["pop"][s["inhabited"] & (field <= standard)].sum())


def candidate_coverage(s: dict, standard: float, batch: int = 120) -> np.ndarray:
    """Boolean [n_candidates, n_cells] coverage within `standard` of each candidate.

    `limit` truncates each search at the service standard, so these stay local and cheap.
    """
    n = len(s["cand_nodes"])
    shape = s["cell_node"].shape
    out = np.zeros((n, shape[0] * shape[1]), dtype=bool)
    for i in range(0, n, batch):
        chunk = s["cand_nodes"][i:i + batch]
        dn = dijkstra(s["csr"], indices=chunk, limit=standard, min_only=False)
        for j in range(len(chunk)):
            f = dn[j][s["cell_node"]] + s["snap"]
            out[i + j] = ((f <= standard) & s["land"]).ravel()
    return out


# ---------------------------------------------------------------- strategies


def strat_mclp_greedy(s: dict, k: int, standard: float, cov: np.ndarray) -> list:
    """Classic greedy maximal-covering: repeatedly take the biggest marginal gain."""
    base = field_from(s, s["fac_nodes"])
    already = ((base <= standard) & s["inhabited"]).ravel()
    popflat = np.where(s["inhabited"].ravel(), s["pop"].ravel(), 0.0)
    picks = []
    for _ in range(k):
        gain = (cov & ~already) @ popflat
        gain[[p for p in picks]] = -1
        best = int(np.argmax(gain))
        picks.append(best)
        already = already | cov[best]
    return picks


def strat_worst_point(s: dict, k: int, standard: float) -> list:
    """No topology at all: place at the worst-served inhabited cell, then recompute."""
    nodes = list(s["fac_nodes"])
    picks = []
    for _ in range(k):
        f = field_from(s, np.array(nodes))
        masked = np.where(s["inhabited"], f, -np.inf)
        rc = np.unravel_index(np.argmax(masked), masked.shape)
        picks.append(nearest_candidate(s, rc, exclude=set(picks)))
        nodes.append(int(s["cand_nodes"][picks[-1]]))
    return picks


def strat_ph(s: dict, k: int, standard: float, mode: str, adaptive: bool) -> list:
    """Place at persistent-homology output.

    mode='persistence' -> death cells of the most persistent H1 classes.
    mode='population'  -> worst-served point of the highest-population pockets.
    """
    nodes = list(s["fac_nodes"])
    picks: list[int] = []
    while len(picks) < k:
        if adaptive:
            _write_field(s, np.array(nodes))
        if mode == "persistence":
            r = analyse(s["resource"], extra=~s["water"])
            targets = [tuple(c) for c in r["network"]["cells"]]
        else:
            rows, _ = pockets(s["resource"], "network", standard)
            targets = []
            for row in rows:
                masked = np.where(row["region"], _current_field(s), -np.inf)
                targets.append(np.unravel_index(np.argmax(masked), masked.shape))
        added = False
        for t in targets:
            c = nearest_candidate(s, t, exclude=set(picks))
            if c not in picks:
                picks.append(c)
                nodes.append(int(s["cand_nodes"][c]))
                added = True
                break
        if not added:
            break
        if not adaptive and len(picks) < k:
            # non-adaptive: take the whole ranked list from the original analysis
            for t in targets[1:]:
                c = nearest_candidate(s, t, exclude=set(picks))
                if c not in picks:
                    picks.append(c)
                    if len(picks) == k:
                        break
            break
    return picks[:k]


def strat_random(s: dict, k: int, seed: int) -> list:
    rng = np.random.default_rng(seed)
    return list(rng.choice(len(s["cand_nodes"]), size=k, replace=False))


# ---------------------------------------------------------------- helpers

_FIELD_CACHE: dict = {}


def _write_field(s: dict, nodes: np.ndarray) -> None:
    """Adaptive PH needs the field on disk, since analyse()/pockets() read the npz."""
    f = field_from(s, nodes)
    d = dict(np.load(DATA / f"fields_{s['resource']}.npz"))
    d["network"] = np.where(np.isfinite(f), f, np.inf)
    np.savez_compressed(DATA / f"fields_{s['resource']}.npz", **d)
    _FIELD_CACHE["f"] = f


def _current_field(s: dict) -> np.ndarray:
    return _FIELD_CACHE.get("f", field_from(s, s["fac_nodes"]))


def nearest_candidate(s: dict, rc, exclude: set[int] | None = None) -> int:
    """Snap a recommendation to the shared candidate grid so every strategy is comparable.

    Snapping must use *network* distance. Grid-index distance picks the site that looks
    adjacent on the raster, which across a canal or a ravine can be kilometres away on
    foot -- so the placed facility fails to cover the point it was meant to serve, the
    same cell stays the worst-served one, and the strategy re-picks it forever.
    """
    exclude = exclude or set()
    src = int(s["cell_node"][rc[0], rc[1]])
    dn = dijkstra(s["csr"], indices=[src], min_only=True)
    dcand = dn[s["cand_nodes"]]
    dcand[list(exclude)] = np.inf
    if np.isfinite(dcand).any():
        return int(np.argmin(dcand))
    # disconnected component: fall back to raster adjacency
    d = np.abs(s["cand_rc"][:, 0] - rc[0]) + np.abs(s["cand_rc"][:, 1] - rc[1]).astype(float)
    d[list(exclude)] = np.inf
    return int(np.argmin(d))


def evaluate(s: dict, picks: list, standard: float) -> list[float]:
    """Population covered after each successive placement."""
    nodes = list(s["fac_nodes"])
    out = [covered_pop(s, field_from(s, np.array(nodes)), standard)]
    for p in picks:
        nodes.append(int(s["cand_nodes"][p]))
        out.append(covered_pop(s, field_from(s, np.array(nodes)), standard))
    return out


def main(resource: str = "libraries") -> None:
    import shutil

    standard = SERVICE_STANDARD_M
    backup = DATA / f"fields_{resource}.npz.bak"
    shutil.copy(DATA / f"fields_{resource}.npz", backup)
    try:
        s = setup(resource)
        print(f"candidates: {len(s['cand_nodes'])} sites at {150 * STRIDE} m spacing")
        print(f"standard  : {standard:.0f} m   existing: {len(s['fac_nodes'])} branches")
        t = time.time()
        cov = candidate_coverage(s, standard)
        print(f"coverage sets precomputed in {time.time() - t:.0f}s\n")

        runs = {
            "MCLP greedy": strat_mclp_greedy(s, K, standard, cov),
            "worst-point (no topology)": strat_worst_point(s, K, standard),
            "PH by persistence": strat_ph(s, K, standard, "persistence", adaptive=False),
            "PH by population": strat_ph(s, K, standard, "population", adaptive=False),
            "PH by population (adaptive)": strat_ph(s, K, standard, "population", True),
        }
        shutil.copy(backup, DATA / f"fields_{resource}.npz")
        s = setup(resource)

        rnd = np.mean([evaluate(s, strat_random(s, K, sd), standard) for sd in range(5)], axis=0)

        base = None
        print(f"{'strategy':30s}" + "".join(f"{f'+{i}':>9s}" for i in range(K + 1)))
        print("-" * (30 + 9 * (K + 1)))
        results = {}
        for name, picks in runs.items():
            vals = evaluate(s, picks, standard)
            results[name] = vals
            base = vals[0] if base is None else base
            print(f"{name:30s}" + "".join(f"{v / 1000:>8.1f}k" for v in vals))
        results["random (mean of 5)"] = list(rnd)
        print(f"{'random (mean of 5)':30s}" + "".join(f"{v / 1000:>8.1f}k" for v in rnd))

        print(f"\nPeople newly covered by k=8 placements (baseline {base / 1000:.1f}k):")
        rank = sorted(results.items(), key=lambda kv: -(kv[1][K] - kv[1][0]))
        for name, vals in rank:
            gain = vals[K] - vals[0]
            print(f"  {name:30s} +{gain:>8,.0f}   "
                  f"({100 * gain / (rank[0][1][K] - rank[0][1][0]):5.1f}% of best)")
    finally:
        shutil.copy(backup, DATA / f"fields_{resource}.npz")
        backup.unlink()


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else "libraries")
