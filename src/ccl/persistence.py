"""Sublevel-set persistent homology of a nearest-facility field.

The sublevel set {x : d(x) <= t} of a Euclidean nearest-facility field is exactly the union
of radius-t balls around the facilities, so its H1 is the Cech coverage picture from the
literature. Substituting network or travel-time distance gives the same construction under
a different metric, which is what the siting benchmark compares against.
"""

import gudhi
import numpy as np

MIN_PERSISTENCE_M = 300.0  # below ~2 grid cells the bars are discretization noise


def h1_diagram(field: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (bars[n,2], death_cells[n,2]) for H1, sorted by decreasing persistence.

    Localization uses the *death* cell, not the birth cell. The birth cell is the saddle
    where the loop closes up, which sits on the rim of the void; the death cell is the last
    point the sublevel set reaches -- the most underserved point, and where you would site
    a facility. Verified against a synthetic ring of 8 points at radius 30: death value
    30.0, death cell exactly the center.
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
