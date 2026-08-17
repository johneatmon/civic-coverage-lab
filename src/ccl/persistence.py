"""Sublevel-set persistent homology of the nearest-facility distance fields.

The sublevel set {x : d(x) <= t} of a Euclidean nearest-facility field is exactly the
union of radius-t balls around the facilities, so its H1 is the Cech coverage picture
from the literature. Swapping in network distance gives the same construction under a
travel-time metric -- which is the whole question. Same machinery both ways, so any
difference in the barcode is attributable to the metric and not to the pipeline.
"""

from pathlib import Path

import gudhi
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

SNAP_MAX_M = 250.0  # cells further than this from the walk network are not walkable land
MIN_PERSISTENCE_M = 300.0  # below ~2 grid cells the bars are discretisation noise


def masked_field(field: np.ndarray, inside: np.ndarray, snap: np.ndarray) -> np.ndarray:
    """Restrict the field to walkable land inside the city; elsewhere +inf."""
    keep = inside & (snap <= SNAP_MAX_M) & np.isfinite(field)
    out = np.full(field.shape, np.inf)
    out[keep] = field[keep]
    return out


def h1_diagram(field: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (bars[n,2], death_cells[n,2]) for H1, sorted by decreasing persistence.

    Localisation uses the *death* cell, not the birth cell. The birth cell is the saddle
    where the loop closes up, which sits on the rim of the void; the death cell is the
    last point the sublevel set reaches, i.e. the most underserved point in the hole --
    which is both what you want to draw on a map and where you would site a facility.
    """
    cc = gudhi.CubicalComplex(top_dimensional_cells=field)
    cc.compute_persistence()
    regular, _essential = cc.cofaces_of_persistence_pairs()

    if len(regular) < 2 or len(regular[1]) == 0:
        return np.empty((0, 2)), np.empty((0, 2), dtype=int)

    pairs = regular[1]  # dimension-1 pairs, flat indices into field
    flat = field.flatten()
    births, deaths = flat[pairs[:, 0]], flat[pairs[:, 1]]
    keep = np.isfinite(births) & np.isfinite(deaths)
    with np.errstate(invalid="ignore"):
        keep &= (deaths - births) >= MIN_PERSISTENCE_M
    pairs, births, deaths = pairs[keep], births[keep], deaths[keep]

    order = np.argsort(-(deaths - births))
    bars = np.column_stack([births[order], deaths[order]])
    rows, cols = np.unravel_index(pairs[order, 1], field.shape)
    return bars, np.column_stack([rows, cols])


def to_xy(cells: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Grid cells (row, col) -> projected (x, y) coordinates."""
    if len(cells) == 0:
        return np.empty((0, 2))
    return np.column_stack([xs[cells[:, 1]], ys[cells[:, 0]]])


def analyse(resource: str) -> dict:
    d = np.load(DATA / f"fields_{resource}.npz")
    xs, ys, inside, snap = d["xs"], d["ys"], d["inside"], d["snap"]

    result = {"xs": xs, "ys": ys}
    for metric in ("euclidean", "network"):
        f = masked_field(d[metric], inside, snap)
        bars, cells = h1_diagram(f)
        result[metric] = {
            "field": f,
            "bars": bars,
            "cells": cells,
            "xy": to_xy(cells, xs, ys),
            "persistence": bars[:, 1] - bars[:, 0] if len(bars) else np.empty(0),
        }
    return result


def bottleneck(a: np.ndarray, b: np.ndarray) -> float:
    return gudhi.bottleneck_distance(a, b) if len(a) and len(b) else float("nan")


def report(resource: str, top_k: int = 8) -> dict:
    r = analyse(resource)
    e, n = r["euclidean"], r["network"]

    print(f"\n{'=' * 74}\n{resource.upper()}\n{'=' * 74}")
    print(f"{'':14s}{'H1 bars':>10s}{'top persist':>14s}{'total persist':>16s}")
    for name, m in (("euclidean", e), ("network", n)):
        p = m["persistence"]
        top = p[0] if len(p) else 0.0
        print(f"{name:14s}{len(m['bars']):>10d}{top:>13.0f}m{p.sum():>15.0f}m")

    print(f"\nbottleneck distance (H1): {bottleneck(e['bars'], n['bars']):.0f} m")

    print(f"\nTop {top_k} holes, by persistence — where they sit and how far they move:")
    print(f"{'#':>3s} {'euclidean (m)':>26s} {'network (m)':>26s} {'shift':>9s}")
    for i in range(top_k):
        ex = f"{e['xy'][i][0]:.0f},{e['xy'][i][1]:.0f}" if i < len(e["xy"]) else "-"
        nx_ = f"{n['xy'][i][0]:.0f},{n['xy'][i][1]:.0f}" if i < len(n["xy"]) else "-"
        ep = f"p={e['persistence'][i]:.0f}" if i < len(e["persistence"]) else ""
        np_ = f"p={n['persistence'][i]:.0f}" if i < len(n["persistence"]) else ""
        if i < len(e["xy"]) and i < len(n["xy"]):
            shift = np.linalg.norm(e["xy"][i] - n["xy"][i])
            shift_s = f"{shift:>8.0f}m"
        else:
            shift_s = "        -"
        print(f"{i + 1:>3d} {ex:>16s} {ep:>9s} {nx_:>16s} {np_:>9s} {shift_s}")

    # Rank-free version of the same question: does each Euclidean hole have a network
    # hole near it at all? Nearest-neighbour match in space.
    if len(e["xy"]) and len(n["xy"]):
        k = min(top_k, len(e["xy"]))
        dists = np.linalg.norm(e["xy"][:k, None, :] - n["xy"][None, :, :], axis=2)
        nearest = dists.min(axis=1)
        print(
            f"\nnearest network hole to each of the top {k} euclidean holes: "
            f"median {np.median(nearest):.0f} m, max {nearest.max():.0f} m"
        )
    return r


if __name__ == "__main__":
    import sys

    report(sys.argv[1] if len(sys.argv) > 1 else "libraries")
