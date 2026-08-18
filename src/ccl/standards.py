"""Underserved population by walker profile, time budget, car access — and slope effect.

Now measured in actual travel time rather than a distance proxy, which is what a
"15 minute neighborhood" policy literally says. Slope enters through the per-profile
speed model, and for the mobility profile through ADA-impassable edges.
"""

import numpy as np

from ccl.build import load
from ccl.cities import (PAR_MAX_GRADE, PROFILES, TIME_BUDGETS_MIN,
                        amenity as get_amenity, distance_m, get)


def flat_underserved(d, pop_field, threshold_m, metric="network"):
    """Old distance-based measure: flat meters, no slope."""
    mask = d["land"] & np.isfinite(d[metric])
    tot = float(d[pop_field][mask].sum())
    return float(d[pop_field][mask & (d[metric] > threshold_m)].sum()), tot


def time_underserved(d, profile, minutes):
    """Slope-aware: beyond the time budget, or with no usable route at all."""
    f = d[f"time_{profile.key}"]
    mask = d["land"]
    tot = float(d[profile.pop_field][mask].sum())
    beyond = mask & ~(f <= minutes * 60.0)  # NaN/inf-safe: unreachable counts as beyond
    unreachable = mask & ~np.isfinite(f)
    return (float(d[profile.pop_field][beyond].sum()), tot,
            float(d[profile.pop_field][unreachable].sum()))


def summary(city_key: str, amenity_key: str = "libraries") -> dict:
    """All the numbers the report needs, in one pass."""
    city, am = get(city_key), get_amenity(amenity_key)
    d = load(city_key, amenity_key)
    out = {"city": city, "amenity": am, "d": d, "headline_min": am.headline_min,
           "n_facilities": int(d["n_facilities"]) if "n_facilities" in d
                           else int(d["fac_nodes"].size)}

    mask = d["land"]
    out["population"] = float(d["population"][mask].sum())
    # restricted to in-city edges: the graph extends past the boundary so that
    # cross-boundary destinations are reachable, but this statistic describes the city
    eic = d["edge_in_city"] if "edge_in_city" in d else np.ones_like(d["edge_grade"], bool)
    out["grade_steep_pct"] = 100.0 * float(
        (np.abs(d["edge_grade"][eic]) > PAR_MAX_GRADE).mean())
    out["elev_range"] = (float(np.nanmin(d["node_elev"])), float(np.nanmax(d["node_elev"])))

    rows = []
    for p in PROFILES:
        r = {"profile": p}
        for m in TIME_BUDGETS_MIN:
            b, t, u = time_underserved(d, p, m)
            fb, ft = flat_underserved(d, p.pop_field, distance_m(p, m))
            r[m] = {"beyond": b, "total": t, "unreachable": u, "pct": 100 * b / t,
                    "flat_beyond": fb, "flat_pct": 100 * fb / ft,
                    "slope_cost": b - fb}
        rows.append(r)
    out["profiles"] = rows

    # Car access at the amenity's own standard, slope-aware.
    adult = PROFILES[0]
    f = d[f"time_{adult.key}"]
    beyond = mask & ~(f <= am.headline_min * 60.0)
    tot_all, tot_no = float(d["households"][mask].sum()), float(d["no_vehicle_hh"][mask].sum())
    b_all, b_no = float(d["households"][beyond].sum()), float(d["no_vehicle_hh"][beyond].sum())
    out["car"] = {
        "no_vehicle": (tot_no, b_no, 100 * b_no / tot_no),
        "has_vehicle": (tot_all - tot_no, b_all - b_no,
                        100 * (b_all - b_no) / (tot_all - tot_no)),
        "all": (tot_all, b_all, 100 * b_all / tot_all),
    }
    return out


def report(city_key: str, amenity_key: str = "libraries") -> None:
    s = summary(city_key, amenity_key)
    d, city = s["d"], s["city"]
    print(f"\n{'=' * 92}\n{city.place.upper()} — {s['n_facilities']} {s['amenity'].label}")
    print(f"elevation {s['elev_range'][0]:.0f}–{s['elev_range'][1]:.0f} m; "
          f"{s['grade_steep_pct']:.1f}% of walk edges steeper than the 5% accessible-route grade")
    print("=" * 92)

    for m in TIME_BUDGETS_MIN:
        print(f"\n--- {m}-minute walk ---")
        print(f"{'profile':28s}{'group':>11s}{'flat (no slope)':>18s}"
              f"{'with slope':>16s}{'of which no route':>19s}")
        for r in s["profiles"]:
            c = r[m]
            print(f"{r['profile'].label:28s}{c['total']:>11,.0f}"
                  f"{c['flat_beyond']:>11,.0f} ({c['flat_pct']:4.1f}%)"
                  f"{c['beyond']:>9,.0f} ({c['pct']:4.1f}%)"
                  f"{c['unreachable']:>14,.0f}")

    print(f"\n--- car access, {s['headline_min']}-minute adult standard (slope-aware) ---")
    print(f"{'households':28s}{'total':>12s}{'beyond':>12s}{'rate':>9s}")
    for k, lab in [("no_vehicle", "no vehicle available"), ("has_vehicle", "has a vehicle"),
                   ("all", "all households")]:
        t, b, p = s["car"][k]
        print(f"{lab:28s}{t:>12,.0f}{b:>12,.0f}{p:>8.1f}%")


if __name__ == "__main__":
    import sys

    args = sys.argv[1:] or ["seattle", "tacoma"]
    amen = "libraries"
    if args and args[0] in ("libraries", "parks"):
        amen, args = args[0], args[1:]
    for k in args:
        report(k, amen)
