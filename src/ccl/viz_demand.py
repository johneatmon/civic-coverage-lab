"""Demand-weighted view: which underserved pockets actually strand people."""

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm

from ccl.rank import SERVICE_STANDARD_M, pockets

ROOT = Path(__file__).resolve().parents[2]
DATA, OUT = ROOT / "data", ROOT / "out"


def plot(resource: str = "libraries", top_k: int = 5) -> Path:
    d = np.load(DATA / f"fields_{resource}.npz")
    dem = np.load(DATA / f"demand_{resource}.npz")
    xs, ys = d["xs"], d["ys"]
    extent = [xs[0], xs[-1], ys[0], ys[-1]]
    fac = gpd.read_file(DATA / f"{resource}.geojson").to_crs("EPSG:32610")

    # Only draw density on analysed land -- the block-group rasters otherwise bleed
    # across Puget Sound and Lake Washington and swamp the figure.
    land = d["inside"] & (d["snap"] <= 250) & np.isfinite(d["network"]) & ~dem["water"]
    dens = np.where(land & (dem["population_density"] > 0),
                    dem["population_density"], np.nan)

    fig, axes = plt.subplots(1, 2, figsize=(15, 9), constrained_layout=True)
    for ax, metric in zip(axes, ("euclidean", "network")):
        rows, meta = pockets(resource, metric, SERVICE_STANDARD_M)
        ax.imshow(dens, origin="lower", extent=extent, cmap="Greys",
                  norm=LogNorm(vmin=200, vmax=np.nanmax(dens)), interpolation="nearest")

        overlay = np.zeros(dens.shape, dtype=bool)
        for r in rows:
            overlay |= r["region"]
        ax.imshow(np.where(overlay, 1.0, np.nan), origin="lower", extent=extent,
                  cmap="autumn_r", alpha=0.5, vmin=0, vmax=1.6, interpolation="nearest")

        ax.scatter(fac.geometry.x, fac.geometry.y, s=44, c="#00b3ff", marker="o",
                   edgecolor="white", linewidth=0.9, zorder=3)
        for i, r in enumerate(rows[:top_k], 1):
            ax.annotate(f"{i}\n{r['population'] / 1000:.0f}k", r["xy"], color="black",
                        fontsize=9, fontweight="bold", ha="center",
                        bbox=dict(boxstyle="round,pad=0.25", fc="#ffe680", ec="black", lw=0.8),
                        zorder=5)

        total = sum(r["population"] for r in rows)
        ax.set_title(f"{metric} distance\n{total:,.0f} people beyond a "
                     f"{SERVICE_STANDARD_M:.0f} m walk "
                     f"({100 * total / 720959:.0f}% of Seattle)", fontsize=12)
        ax.set_xticks([]); ax.set_yticks([])

    fig.suptitle(f"Seattle {resource}: underserved pockets, shaded by population density\n"
                 "orange = beyond the service standard; labels give people stranded",
                 fontsize=14, fontweight="bold")
    OUT.mkdir(exist_ok=True)
    path = OUT / f"demand_{resource}.png"
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path


if __name__ == "__main__":
    import sys

    print(plot(sys.argv[1] if len(sys.argv) > 1 else "libraries"))
