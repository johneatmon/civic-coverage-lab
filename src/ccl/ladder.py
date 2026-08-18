"""The measurement ladder: radius -> network -> terrain -> mobility profile.

The project's original claim was that each modeling step changes the answer. That is only
demonstrable if the naive baseline is actually computed, so this quantifies the divergence
rung by rung. Rungs 1-3 hold the population constant, so the differences are attributable
purely to how access is measured. Rung 4 changes both the model and the population it
applies to, which is the point of it.
"""

import numpy as np

from ccl.build import load
from ccl.cities import PROFILES, amenity as get_amenity, distance_m, get

ADULT, MOBILITY = PROFILES[0], PROFILES[2]


def rungs(city_key: str, amenity_key: str = "libraries") -> list[dict]:
    am = get_amenity(amenity_key)
    MINUTES = am.headline_min
    RADIUS_M = distance_m(ADULT, MINUTES)
    d = load(city_key, amenity_key)
    m = d["land"]
    pop, amb = d["population"], d["pop_ambulatory"]
    tot, tot_amb = float(pop[m].sum()), float(amb[m].sum())
    t_adult, t_mob = d["time_adult"], d["time_mobility"]
    budget = MINUTES * 60.0

    def pct(mask, weight, total):
        return 100.0 * float(weight[mask].sum()) / total

    out = [
        {"name": "1. Straight-line radius",
         "detail": f"{RADIUS_M:,.0f} m as the crow flies",
         "pct": pct(m & (d["euclidean"] > RADIUS_M), pop, tot),
         "n": float(pop[m & (d["euclidean"] > RADIUS_M)].sum()), "total": tot},
        {"name": "2. + street network",
         "detail": f"{RADIUS_M:,.0f} m along the walk graph",
         "pct": pct(m & (d["network"] > RADIUS_M), pop, tot),
         "n": float(pop[m & (d["network"] > RADIUS_M)].sum()), "total": tot},
        {"name": "3. + terrain",
         "detail": f"{MINUTES} min at 3 mph, slope-adjusted",
         "pct": pct(m & ~(t_adult <= budget), pop, tot),
         "n": float(pop[m & ~(t_adult <= budget)].sum()), "total": tot},
        {"name": "4. + mobility profile",
         "detail": f"{MINUTES} min at 0.80 m/s, 5% max grade",
         "pct": pct(m & ~(t_mob <= budget), amb, tot_amb),
         "n": float(amb[m & ~(t_mob <= budget)].sum()), "total": tot_amb},
    ]
    for i, r in enumerate(out):
        r["delta"] = 0.0 if i == 0 else r["pct"] - out[i - 1]["pct"]
    return out


def main(keys, amenity_key="libraries") -> None:
    for k in keys:
        rs = rungs(k, amenity_key)
        print(f"\n{'=' * 86}\n{get(k).place.upper()} — how much does each modeling step "
              f"change the answer?\n{'=' * 86}")
        print(f"{'rung':24s}{'measure':34s}{'underserved':>14s}{'step':>10s}")
        for r in rs:
            step = "" if r["delta"] == 0 else f"{r['delta']:+.1f} pp"
            print(f"{r['name']:24s}{r['detail']:34s}"
                  f"{r['n']:>9,.0f} {r['pct']:>4.1f}%{step:>10s}")
        r1, r3 = rs[0]["pct"], rs[2]["pct"]
        print(f"\n  straight-line understates the underserved population by "
              f"{r3 - r1:.1f} points ({rs[2]['n'] - rs[0]['n']:+,.0f} people)")
        print(f"  and for residents with an ambulatory difficulty the gap is "
              f"{rs[3]['pct'] - r1:.1f} points")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:] or ["seattle", "tacoma", "phoenix"]
    amen = "libraries"
    if args and args[0] in ("libraries", "parks"):
        amen, args = args[0], args[1:]
    main(args, amen)
