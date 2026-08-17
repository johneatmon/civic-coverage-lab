"""Underserved population by walking-speed profile, time budget, and car access.

A time-based service standard ("everyone within a 10 minute walk") is not one distance.
It is a different distance for every kind of walker, and each of those distances applies
to a different population. This resolves the policy sentence into the numbers it actually
implies.
"""

import numpy as np

from ccl.build import load
from ccl.cities import PROFILES, TIME_BUDGETS_MIN, distance_m, get


def underserved(d: dict, metric: str, pop_field: str, threshold: float) -> tuple[float, float]:
    """(people/households beyond the threshold, total in the analysed area)."""
    mask = d["land"] & np.isfinite(d[metric])
    total = float(d[pop_field][mask].sum())
    beyond = float(d[pop_field][mask & (d[metric] > threshold)].sum())
    return beyond, total


def report(city_key: str) -> None:
    city = get(city_key)
    d = load(city_key)

    print(f"\n{'=' * 84}")
    print(f"{city.place.upper()} — {int(d['fac_nodes'].size)} library locations")
    print(f"{'=' * 84}")

    print("\nA time standard is not one distance:\n")
    print(f"{'profile':30s}{'speed':>10s}" +
          "".join(f"{f'{m} min':>12s}" for m in TIME_BUDGETS_MIN))
    for p in PROFILES:
        print(f"{p.label:30s}{p.speed_mps:>8.2f}m/s" +
              "".join(f"{distance_m(p, m):>10,.0f} m" for m in TIME_BUDGETS_MIN))

    for metric in ("network", "euclidean"):
        print(f"\n{'-' * 84}\nUnderserved by profile — {metric} distance\n{'-' * 84}")
        print(f"{'profile':30s}{'relevant pop':>14s}" +
              "".join(f"{f'beyond {m} min':>20s}" for m in TIME_BUDGETS_MIN))
        for p in PROFILES:
            cells = []
            total = 0.0
            for m in TIME_BUDGETS_MIN:
                b, total = underserved(d, metric, p.pop_field, distance_m(p, m))
                cells.append(f"{b:>11,.0f} ({100 * b / total:4.1f}%)")
            print(f"{p.label:30s}{total:>14,.0f}" + "".join(f"{c:>20s}" for c in cells))

    # Car access. Walking distance binds hardest on households without a car; everyone
    # else has an alternative. Reported as households, which is how ACS measures it.
    adult = next(p for p in PROFILES if p.key == "adult")
    print(f"\n{'-' * 84}\nCar access, at the 15-minute adult standard "
          f"({distance_m(adult, 15):,.0f} m) — network distance\n{'-' * 84}")
    thr = distance_m(adult, 15)
    mask = d["land"] & np.isfinite(d["network"])
    beyond = mask & (d["network"] > thr)
    hh_all, hh_no = d["households"], d["no_vehicle_hh"]
    tot_all, tot_no = float(hh_all[mask].sum()), float(hh_no[mask].sum())
    b_all, b_no = float(hh_all[beyond].sum()), float(hh_no[beyond].sum())
    tot_car, b_car = tot_all - tot_no, b_all - b_no
    print(f"{'households':30s}{'total':>14s}{'beyond standard':>20s}{'rate':>10s}")
    print(f"{'no vehicle available':30s}{tot_no:>14,.0f}{b_no:>20,.0f}"
          f"{100 * b_no / tot_no:>9.1f}%")
    print(f"{'has a vehicle':30s}{tot_car:>14,.0f}{b_car:>20,.0f}"
          f"{100 * b_car / tot_car:>9.1f}%")
    print(f"{'all households':30s}{tot_all:>14,.0f}{b_all:>20,.0f}"
          f"{100 * b_all / tot_all:>9.1f}%")

    for m in TIME_BUDGETS_MIN:
        t = distance_m(adult, m)
        bm = mask & (d["network"] > t)
        n = float(hh_no[bm].sum())
        print(f"  car-free households beyond {m:2d} min ({t:,.0f} m): {n:>8,.0f} "
              f"({100 * n / tot_no:.1f}%)")


if __name__ == "__main__":
    import sys

    for k in sys.argv[1:] or ["seattle", "tacoma"]:
        report(k)
    print("\nNOTE: distances are along the walk graph with no slope penalty. Both cities "
          "are hilly,\nso the mobility-difficulty rows understate the real barrier.")
