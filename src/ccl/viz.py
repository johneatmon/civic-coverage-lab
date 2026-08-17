"""Side-by-side map of the two coverage fields and the holes each metric finds."""

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np

from ccl.persistence import analyse

ROOT = Path(__file__).resolve().parents[2]
DATA, OUT = ROOT / "data", ROOT / "out"


def plot(resource: str = "libraries", top_k: int = 10) -> Path:
    r = analyse(resource)
    xs, ys = r["xs"], r["ys"]
    fac = gpd.read_file(DATA / f"{resource}.geojson").to_crs("EPSG:32610")
    extent = [xs[0], xs[-1], ys[0], ys[-1]]

    vmax = np.nanmax([m["field"][np.isfinite(m["field"])].max()
                      for m in (r["euclidean"], r["network"])])

    fig, axes = plt.subplots(1, 2, figsize=(15, 9), constrained_layout=True)
    for ax, metric in zip(axes, ("euclidean", "network")):
        m = r[metric]
        f = np.where(np.isfinite(m["field"]), m["field"], np.nan)
        im = ax.imshow(f, origin="lower", extent=extent, cmap="magma",
                       vmin=0, vmax=vmax, interpolation="nearest")
        ax.scatter(fac.geometry.x, fac.geometry.y, s=26, c="#00e5ff",
                   edgecolor="black", linewidth=0.5, label=f"{resource} ({len(fac)})", zorder=3)

        xy, pers = m["xy"][:top_k], m["persistence"][:top_k]
        if len(xy):
            ax.scatter(xy[:, 0], xy[:, 1], s=90 + 300 * pers / pers.max(),
                       facecolor="none", edgecolor="#39ff14", linewidth=2.2,
                       label=f"H1 holes ({len(m['bars'])})", zorder=4)
            for i, (px, py) in enumerate(xy):
                ax.annotate(str(i + 1), (px, py), color="#39ff14", fontsize=9,
                            fontweight="bold", xytext=(7, 5), textcoords="offset points")

        n_all = len(m["bars"])
        total = m["persistence"].sum()
        ax.set_title(f"{metric} distance\n{n_all} H1 holes, total persistence {total:.0f} m",
                     fontsize=12)
        ax.set_xticks([]); ax.set_yticks([])
        ax.legend(loc="lower left", fontsize=9, framealpha=0.85)

    fig.colorbar(im, ax=axes, shrink=0.65, label="distance to nearest facility (m)")
    fig.suptitle(
        f"Seattle {resource.replace('_', ' ')}: coverage holes under two metrics",
        fontsize=15, fontweight="bold",
    )
    OUT.mkdir(exist_ok=True)
    path = OUT / f"holes_{resource}.png"
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path


if __name__ == "__main__":
    import sys

    print(plot(sys.argv[1] if len(sys.argv) > 1 else "libraries"))
