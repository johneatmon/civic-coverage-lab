"""Rank underserved pockets by who is actually stranded in them.

Persistence measures the geometric size of a hole. It says nothing about whether anyone
lives there -- which is why the unweighted spike ranked an industrial strip and a floating
bridge above residential neighbourhoods.

A note on how a hole's *extent* is defined, because the obvious choice is wrong. The void
a class encloses is the component of {d > birth} containing the death cell, but at low
birth values that superlevel set is still globally connected, so the region swallows every
underserved cell in the city at once (measured: 167 km^2, 616k people, for a single hole).
Instead, pockets are cut at a policy service standard -- cells beyond an S-metre walk --
and persistent homology is used for what it is uniquely good at: saying which pockets are
topologically *enclosed* by coverage rather than merely hanging off the city edge.
"""

from pathlib import Path

import numpy as np
from scipy import ndimage

from ccl.persistence import analyse, base_mask

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

SERVICE_STANDARD_M = 1200.0  # ~15 min walk at 1.4 m/s; beyond this a cell is underserved
CONN4 = ndimage.generate_binary_structure(2, 1)  # matches cubical face-adjacency


def pockets(resource: str, metric: str, standard: float) -> tuple[list[dict], dict]:
    d = np.load(DATA / f"fields_{resource}.npz")
    dem = np.load(DATA / f"demand_{resource}.npz")
    valid = base_mask(d, ~dem["water"]) & np.isfinite(d[metric])

    r = analyse(resource, extra=~dem["water"])
    m = r[metric]

    underserved = (m["field"] > standard) & valid
    labels, n = ndimage.label(underserved, structure=CONN4)

    # Which pockets contain the death cell of a finite H1 class -> enclosed by coverage.
    enclosed: dict[int, float] = {}
    for bar, cell in zip(m["bars"], m["cells"]):
        lab = int(labels[cell[0], cell[1]])
        if lab:
            enclosed[lab] = max(enclosed.get(lab, 0.0), float(bar[1] - bar[0]))

    rows = []
    for lab in range(1, n + 1):
        region = labels == lab
        if region.sum() < 2:
            continue
        # Anchor the pocket at its worst-served cell, not its centroid: these regions are
        # large and irregular, so a centroid frequently lands outside the pocket entirely
        # and gives it a misleading neighbourhood name.
        masked = np.where(region, m["field"], -np.inf)
        wr, wc = np.unravel_index(np.argmax(masked), masked.shape)
        rows.append({
            "label": lab,
            "area_km2": float(region.sum()) * 0.0225,
            "worst_m": float(m["field"][region].max()),
            "population": float(dem["population"][region].sum()),
            "below_poverty": float(dem["below_poverty"][region].sum()),
            "no_vehicle_hh": float(dem["no_vehicle_hh"][region].sum()),
            "enclosed": lab in enclosed,
            "persistence": enclosed.get(lab, 0.0),
            "xy": (r["xs"][wc], r["ys"][wr]),
            "region": region,
        })
    rows.sort(key=lambda x: -x["population"])
    return rows, {"n_pockets": n, "n_enclosed": len(enclosed)}


def main(resource: str = "libraries", top_k: int = 12) -> None:
    for metric in ("euclidean", "network"):
        rows, meta = pockets(resource, metric, SERVICE_STANDARD_M)
        tot = sum(r["population"] for r in rows)
        print(f"\n{'=' * 88}")
        print(f"{resource.upper()} / {metric} — pockets beyond a {SERVICE_STANDARD_M:.0f} m walk")
        print(f"{'=' * 88}")
        print(f"{meta['n_pockets']} pockets, {meta['n_enclosed']} topologically enclosed; "
              f"{tot:,.0f} people underserved "
              f"({100 * tot / 720959:.1f}% of the analysed population)")
        if not rows:
            continue
        print(f"\n{'#':>2} {'area':>8} {'worst':>7} {'pop':>8} {'poverty':>8} "
              f"{'no-car HH':>10} {'enclosed':>9} {'persist':>8}")
        for i, r in enumerate(rows[:top_k], 1):
            enc = "yes" if r["enclosed"] else "-"
            pers = f"{r['persistence']:.0f}m" if r["enclosed"] else ""
            print(f"{i:>2} {r['area_km2']:>6.2f}km² {r['worst_m']:>6.0f}m "
                  f"{r['population']:>8,.0f} {r['below_poverty']:>8,.0f} "
                  f"{r['no_vehicle_hh']:>10,.0f} {enc:>9} {pers:>8}")

    print(f"\n{'=' * 88}\nSensitivity to the service standard (network metric)\n{'=' * 88}")
    print(f"{'standard':>10} {'pockets':>9} {'enclosed':>9} {'people underserved':>20}")
    for s in (600, 800, 1000, 1200, 1600, 2000):
        rows, meta = pockets(resource, "network", float(s))
        print(f"{s:>9}m {meta['n_pockets']:>9} {meta['n_enclosed']:>9} "
              f"{sum(r['population'] for r in rows):>20,.0f}")


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else "libraries")
