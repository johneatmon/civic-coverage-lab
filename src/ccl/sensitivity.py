"""How much does the grade-exclusion finding depend on the 5% cutoff?

Two separate questions, and they are not equally important:

1. Threshold — does the stranded population move a lot across the plausible range? Each
   grade below has a real meaning: 1:20 is the accessible-route/PAR limit, 1:12 is the
   maximum for a ramp or curb ramp, and the steeper rows approximate what PROWAG's
   adjacent-street exception effectively permits on a hillside sidewalk.
2. Model form — treating a steep segment as *impassable* is a modelling choice. Real
   routes have switchbacks, and street centreline grade is not sidewalk grade. Under a
   soft penalty nobody is stranded; they just face a longer trip. The question that
   actually matters is how long that trip is. If the "stranded" cohort faces 25 minutes
   under a soft model, the hard cutoff is overstating the finding. If they face 90, the
   substance survives regardless of the word "impassable".
"""

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from ccl.build import load
from ccl.cities import PROFILES, get
from ccl.elevation import speed

MOBILITY = PROFILES[2]
GRADES = [0.04, 0.05, 0.0625, 0.0833, 0.10, 0.125, 0.15, None]
GRADE_LABEL = {0.04: "4.0%", 0.05: "1:20 (5%) route", 0.0625: "1:16 (6.3%)",
               0.0833: "1:12 (8.3%) ramp", 0.10: "1:10 (10%)", 0.125: "1:8 (12.5%)",
               0.15: "15% (street grade)", None: "no cutoff"}
HEADLINE = 0.05
PENALTIES = [1, 2, 5, 10, 25, np.inf]


def time_field(d, csr, coo, flat_mps, max_grade, penalty=np.inf):
    """Travel-time field. `penalty` is the cost multiplier on above-threshold segments;
    np.inf reproduces the hard cutoff."""
    grade, length = d["edge_grade"], coo.data
    t = length / speed(grade, flat_mps)
    if max_grade is not None:
        steep = np.abs(grade) > max_grade
        if np.isinf(penalty):
            t = np.where(steep, np.inf, t)
        else:
            t = np.where(steep, t * penalty, t)
    keep = np.isfinite(t)
    m = csr_matrix((t[keep], (coo.row[keep], coo.col[keep])), shape=csr.shape)
    tn = dijkstra(m.T.tocsr(), indices=d["fac_nodes"], min_only=True)
    return np.where(d["land"], tn[d["cell_node"]] + d["snap"] / flat_mps, np.inf)


def analyse(city_key: str) -> None:
    city, d = get(city_key), load(city_key)
    csr = csr_matrix((d["csr_data"], d["csr_indices"], d["csr_indptr"]),
                     shape=tuple(d["csr_shape"]))
    coo = csr.tocoo()
    pop = d["pop_ambulatory"]
    land = d["land"]
    total = float(pop[land].sum())
    grade = d["edge_grade"]

    print(f"\n{'=' * 88}\n{city.place.upper()} — ambulatory-difficulty population "
          f"{total:,.0f}\n{'=' * 88}")

    print("\n1. THRESHOLD SWEEP (hard cutoff: above-grade segments impassable)")
    print(f"{'max grade':>16s}{'edges blocked':>15s}{'no route':>14s}"
          f"{'beyond 15 min':>16s}{'beyond 30 min':>16s}")
    base_stranded = None
    for g in GRADES:
        f = time_field(d, csr, coo, MOBILITY.speed_mps, g)
        blocked = 0.0 if g is None else 100 * float((np.abs(grade) > g).mean())
        nor = float(pop[land & ~np.isfinite(f)].sum())
        b15 = float(pop[land & ~(f <= 900)].sum())
        b30 = float(pop[land & ~(f <= 1800)].sum())
        if g == HEADLINE:
            base_stranded = land & ~np.isfinite(f)
        print(f"{GRADE_LABEL[g]:>16s}{blocked:>14.1f}%{nor:>10,.0f}"
              f"{100 * nor / total:>5.0f}%{b15:>11,.0f}{100 * b15 / total:>5.0f}%"
              f"{b30:>11,.0f}{100 * b30 / total:>5.0f}%")

    print("\n2. MODEL FORM at the 5% accessible-route grade")
    print("   (cost multiplier on above-grade segments; inf = the hard cutoff)")
    print(f"{'penalty':>16s}{'no route':>14s}{'beyond 15 min':>16s}{'beyond 30 min':>16s}")
    for p in PENALTIES:
        f = time_field(d, csr, coo, MOBILITY.speed_mps, HEADLINE, p)
        nor = float(pop[land & ~np.isfinite(f)].sum())
        b15 = float(pop[land & ~(f <= 900)].sum())
        b30 = float(pop[land & ~(f <= 1800)].sum())
        lab = "inf (hard)" if np.isinf(p) else f"{p}x"
        print(f"{lab:>16s}{nor:>10,.0f}{100 * nor / total:>4.0f}%"
              f"{b15:>11,.0f}{100 * b15 / total:>5.0f}%"
              f"{b30:>11,.0f}{100 * b30 / total:>5.0f}%")

    print("\n3. WHAT DO THE 'STRANDED' ACTUALLY FACE?")
    print("   Travel time for exactly the cells the hard cutoff calls unreachable,")
    print("   recomputed with a soft penalty instead.")
    n_stranded = float(pop[base_stranded].sum())
    print(f"   cohort: {n_stranded:,.0f} people ({100 * n_stranded / total:.0f}% of group)")
    print(f"\n{'penalty':>16s}{'median':>10s}{'p90':>9s}{'max':>9s}{'still >60 min':>15s}")
    for p in [1, 2, 5, 10, 25]:
        f = time_field(d, csr, coo, MOBILITY.speed_mps, HEADLINE, p)
        v = f[base_stranded] / 60.0
        ok = np.isfinite(v)
        w = pop[base_stranded][ok]
        over = float(w[v[ok] > 60].sum())
        print(f"{f'{p}x':>16s}{np.median(v[ok]):>9.0f}m{np.percentile(v[ok], 90):>8.0f}m"
              f"{v[ok].max():>8.0f}m{100 * over / n_stranded:>14.0f}%")

    # Detour cost: how much longer is the low-grade route than the unconstrained one?
    f_free = time_field(d, csr, coo, MOBILITY.speed_mps, None)
    f_ada = time_field(d, csr, coo, MOBILITY.speed_mps, HEADLINE)
    both = land & np.isfinite(f_free) & np.isfinite(f_ada)
    ratio = f_ada[both] / np.maximum(f_free[both], 1)
    w = pop[both]
    print(f"\n4. DETOUR COST for those who DO keep a low-grade route")
    print(f"   population-weighted median ratio (<=5% route / unconstrained): "
          f"{np.median(np.repeat(ratio, np.maximum(w.astype(int), 0)) if w.sum() > 0 else ratio):.2f}x")
    print(f"   share of that population facing >1.5x: "
          f"{100 * float(w[ratio > 1.5].sum()) / float(w.sum()):.0f}%")




def stranded_profile(city_key: str) -> dict:
    """Compact summary for the report: how robust is the 'no route' finding?

    Returns the ADA-cutoff stranded count, the range of that count across plausible
    thresholds, and what the stranded cohort faces with NO slope penalty at all -- the
    most generous assumption available.
    """
    d = load(city_key)
    csr = csr_matrix((d["csr_data"], d["csr_indices"], d["csr_indptr"]),
                     shape=tuple(d["csr_shape"]))
    coo = csr.tocoo()
    pop, land = d["pop_ambulatory"], d["land"]

    f_ada = time_field(d, csr, coo, MOBILITY.speed_mps, HEADLINE)
    stranded = land & ~np.isfinite(f_ada)
    count = float(pop[stranded].sum())

    counts = []
    for g in (0.04, 0.05, 0.0625, 0.0833, 0.10, 0.125, 0.15):
        f = time_field(d, csr, coo, MOBILITY.speed_mps, g)
        counts.append(float(pop[land & ~np.isfinite(f)].sum()))

    f_free = time_field(d, csr, coo, MOBILITY.speed_mps, None)
    v = f_free[stranded] / 60.0
    ok = np.isfinite(v)
    w = pop[stranded][ok]
    return {
        "count": count,
        "range": (min(counts), max(counts)),
        "median_min_no_penalty": float(np.median(v[ok])) if ok.any() else float("nan"),
        "pct_over_60_no_penalty": (100 * float(w[v[ok] > 60].sum()) / max(count, 1)),
    }


if __name__ == "__main__":
    import sys

    for k in sys.argv[1:] or ["seattle", "tacoma"]:
        analyse(k)
