"""How much a time-based service standard varies by who is doing the walking."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from ccl.build import load
from ccl.cities import PROFILES, TIME_BUDGETS_MIN, distance_m, get
from ccl.standards import time_underserved

OUT = Path(__file__).resolve().parents[2] / "assets"  # committed: README embeds it
COLORS = {10: "#e4572e", 15: "#f5b841"}


def plot(city_keys=("seattle", "tacoma"), amenity_key="libraries") -> Path:
    fig, axes = plt.subplots(1, len(city_keys), figsize=(6.6 * len(city_keys), 6.4),
                             constrained_layout=True, sharex=True)
    axes = np.atleast_1d(axes)

    for ax, key in zip(axes, city_keys):
        d, city = load(key, amenity_key), get(key)
        y = np.arange(len(PROFILES))
        h = 0.36
        for i, minutes in enumerate(TIME_BUDGETS_MIN):
            pct, labels = [], []
            for p in PROFILES:
                b, t, _ = time_underserved(d, p, minutes)
                pct.append(100 * b / t)
                labels.append(f"{b:,.0f}")
            off = (i - 0.5) * h
            bars = ax.barh(y + off, pct, height=h, color=COLORS[minutes],
                           edgecolor="black", linewidth=0.6,
                           label=f"{minutes} min walk")
            for bar, lab in zip(bars, labels):
                ax.text(bar.get_width() - 1.5, bar.get_y() + bar.get_height() / 2, lab,
                        va="center", ha="right", fontsize=8.5, fontweight="bold",
                        color="black")

        ax.set_yticks(y)
        ax.set_yticklabels([f"{p.label}\n{p.speed_mps:.2f} m/s  →  "
                            f"{distance_m(p, 10):,.0f}/{distance_m(p, 15):,.0f} m"
                            for p in PROFILES], fontsize=9)
        ax.invert_yaxis()
        ax.set_xlim(0, 100)
        ax.set_xlabel("% of that group beyond a walk to the nearest library")
        b15, t15, _ = time_underserved(d, PROFILES[0], 15)
        cov = 100 * (1 - b15 / t15)
        ax.set_title(f"{city.place.split(',')[0]} — {int(d['fac_nodes'].size)} branches\n"
                     f"{cov:.0f}% of adults meet the 15-minute standard", fontsize=12)
        ax.grid(axis="x", alpha=0.25)
        ax.set_axisbelow(True)
        ax.legend(loc="lower right", fontsize=9)

    fig.suptitle("A time-based service standard is not one distance\n"
                 "same policy sentence, different catchment for every kind of walker",
                 fontsize=14, fontweight="bold")
    OUT.mkdir(exist_ok=True)
    path = OUT / (f"standards_by_profile_{amenity_key}.png" if amenity_key != "libraries"
                  else "standards_by_profile.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return path


if __name__ == "__main__":
    import sys
    print(plot(amenity_key=(sys.argv[1] if len(sys.argv) > 1 else "libraries")))
