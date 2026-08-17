"""Does PH win under *any* objective, or does MCLP dominate outright?

Scoring siting strategies only on population covered is rigged in MCLP's favour: that is
the objective MCLP directly optimises, and no diagnostic should be expected to beat a
direct optimiser on its own loss function. The interesting question is whether persistent
homology wins on an objective it is naturally suited to.

Coverage is a max-sum objective and rewards dense areas. Worst-case walk distance is a
minimax (p-centre) objective and rewards reaching the isolated -- which is exactly what a
topological hole detector points at. If PH loses here too, it has no siting case at all.
"""

import shutil

import numpy as np

from ccl.mclp import (DATA, K, candidate_coverage, evaluate, field_from, setup,
                      strat_mclp_greedy, strat_ph, strat_random, strat_worst_point)
from ccl.rank import SERVICE_STANDARD_M as S


def score(s: dict, picks: list) -> dict:
    nodes = list(s["fac_nodes"]) + [int(s["cand_nodes"][p]) for p in picks]
    f = field_from(s, np.array(nodes))
    inh = s["inhabited"] & np.isfinite(f)
    d, w = f[inh], s["pop"][inh]
    order = np.argsort(d)
    d, w = d[order], w[order]
    cw = np.cumsum(w) / w.sum()
    dem = np.load(DATA / f"demand_{s['resource']}.npz")
    return {
        "covered": float(w[d <= S].sum()),
        "worst": float(d.max()),
        "p95": float(d[np.searchsorted(cw, 0.95)]),
        "mean": float((d * w).sum() / w.sum()),
        "nocar": float(dem["no_vehicle_hh"][inh][order][d <= S].sum()),
    }


def main(resource: str = "libraries") -> None:
    backup = DATA / f"fields_{resource}.npz.bak"
    shutil.copy(DATA / f"fields_{resource}.npz", backup)
    try:
        s = setup(resource)
        cov = candidate_coverage(s, S)
        strategies = {}
        for name, fn in [
            ("MCLP greedy", lambda: strat_mclp_greedy(s, K, S, cov)),
            ("worst-point (no topology)", lambda: strat_worst_point(s, K, S)),
            ("PH by persistence", lambda: strat_ph(s, K, S, "persistence", False)),
            ("PH by population (adaptive)", lambda: strat_ph(s, K, S, "population", True)),
        ]:
            shutil.copy(backup, DATA / f"fields_{resource}.npz")
            strategies[name] = fn()
        shutil.copy(backup, DATA / f"fields_{resource}.npz")
        s = setup(resource)

        base = score(s, [])
        rows = {n: score(s, p) for n, p in strategies.items()}
        rnd = [score(s, strat_random(s, K, sd)) for sd in range(5)]
        rows["random (mean of 5)"] = {k: float(np.mean([r[k] for r in rnd])) for k in base}

        print(f"\nAfter siting k={K} new branches (existing 28 fixed)\n" + "=" * 96)
        print(f"{'strategy':30s}{'covered':>11s}{'car-free HH':>13s}"
              f"{'worst walk':>12s}{'p95 walk':>11s}{'mean walk':>11s}")
        print(f"{'(baseline, no new branches)':30s}{base['covered']:>10,.0f} "
              f"{base['nocar']:>12,.0f}{base['worst']:>11,.0f}m{base['p95']:>10,.0f}m"
              f"{base['mean']:>10,.0f}m")
        print("-" * 96)
        for n, r in rows.items():
            print(f"{n:30s}{r['covered']:>10,.0f} {r['nocar']:>12,.0f}"
                  f"{r['worst']:>11,.0f}m{r['p95']:>10,.0f}m{r['mean']:>10,.0f}m")

        print(f"\n{'improvement vs baseline':30s}{'covered':>11s}{'car-free HH':>13s}"
              f"{'worst walk':>12s}{'p95 walk':>11s}")
        print("-" * 96)
        for n, r in rows.items():
            print(f"{n:30s}{r['covered'] - base['covered']:>+10,.0f} "
                  f"{r['nocar'] - base['nocar']:>+12,.0f}"
                  f"{r['worst'] - base['worst']:>+10,.0f}m"
                  f"{r['p95'] - base['p95']:>+9,.0f}m")

        print("\nBest per objective (worst/p95: most negative wins):")
        for obj, better in [("covered", max), ("nocar", max), ("worst", min), ("p95", min)]:
            win = better(rows.items(), key=lambda kv: kv[1][obj])
            print(f"  {obj:12s} -> {win[0]}")
    finally:
        shutil.copy(backup, DATA / f"fields_{resource}.npz")
        backup.unlink()


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else "libraries")
