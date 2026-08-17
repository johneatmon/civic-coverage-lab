"""Per-city PDF report — the tool's deliverable.

One command per city produces a self-contained document a planner can circulate:
coverage maps, the walker-profile breakdown, the slope/ADA finding, the underserved
pockets with population counts, and the siting benchmark.
"""

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import ListedColormap, LogNorm
from scipy import ndimage

from ccl.bench import field_from as bench_field
from ccl.bench import results as bench_results
from ccl.build import DATA
from ccl.cities import PROFILES, TIME_BUDGETS_MIN, get
from ccl.sensitivity import stranded_profile
from ccl.standards import summary

OUT = Path(__file__).resolve().parents[2] / "out"
PAGE = (8.27, 11.69)  # A4 portrait
INK = "#1a1a1a"
ACCENT = "#c1440e"


def _footer(fig, city, page):
    fig.text(0.5, 0.022, f"Civic Coverage Lab · {city.place} · page {page}",
             ha="center", fontsize=7.5, color="#777")


def _title(fig, text, sub=None):
    fig.text(0.08, 0.945, text, fontsize=17, fontweight="bold", color=INK)
    if sub:
        fig.text(0.08, 0.921, sub, fontsize=9.5, color="#555")
    fig.add_artist(plt.Line2D([0.08, 0.92], [0.911, 0.911], color=ACCENT, lw=1.6))


def _para(fig, y, text, size=9.5, weight="normal", color=INK):
    fig.text(0.08, y, text, fontsize=size, va="top", color=color, wrap=True,
             fontweight=weight, linespacing=1.55)


def _map(ax, s, values, title, cmap="magma_r", norm=None, vmax=None, unreachable=None):
    d = s["d"]
    xs, ys = d["xs"], d["ys"]
    extent = [xs[0], xs[-1], ys[0], ys[-1]]
    arr = np.where(d["land"], values, np.nan)
    im = ax.imshow(arr, origin="lower", extent=extent, cmap=cmap, norm=norm,
                   vmin=None if norm else 0, vmax=None if norm else vmax,
                   interpolation="nearest")
    if unreachable is not None and unreachable.any():
        # explicit single colour -- a colormap here silently renders magenta at vmax
        ax.imshow(np.where(unreachable, 1.0, np.nan), origin="lower", extent=extent,
                  cmap=ListedColormap(["#00e5ff"]), vmin=0, vmax=1, alpha=0.95,
                  interpolation="nearest")
    fac = gpd.read_file(DATA / f"{s['city'].key}_facilities.geojson").to_crs(s["city"].crs)
    ax.scatter(fac.geometry.x, fac.geometry.y, s=30, c="#00d4ff", marker="o",
               edgecolor="black", linewidth=0.7, zorder=4)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(title, fontsize=10.5, color=INK)
    for sp in ax.spines.values():
        sp.set_color("#bbb")
    return im


def build_report(city_key: str, k: int = 8) -> Path:
    city = get(city_key)
    S = summary(city_key)
    d = S["d"]
    s = {"d": d, "city": city}
    adult = PROFILES[0]
    OUT.mkdir(exist_ok=True)
    path = OUT / f"report_{city_key}.pdf"

    t15 = d[f"time_{adult.key}"] / 60.0
    covered_pct = 100 * (1 - S["profiles"][0][15]["pct"] / 100)

    with PdfPages(path) as pdf:
        # ---------------------------------------------------------------- page 1
        fig = plt.figure(figsize=PAGE)
        fig.text(0.08, 0.88, "Library walking access", fontsize=27, fontweight="bold",
                 color=INK)
        fig.text(0.08, 0.845, city.place, fontsize=15, color=ACCENT)
        fig.add_artist(plt.Line2D([0.08, 0.92], [0.83, 0.83], color=ACCENT, lw=2))

        c = S["profiles"][0][15]
        m = S["profiles"][2][15]
        st = stranded_profile(city_key)
        headline = [
            (f"{covered_pct:.0f}%", "of residents can reach a library within a\n"
                                    "15-minute walk (slope-aware travel time)"),
            (f"{c['beyond']:,.0f}", "people are beyond that 15-minute standard"),
            (f"{m['pct']:.0f}%", "of residents with an ambulatory difficulty are\n"
                                 "beyond a 15-minute walk"),
            (f"{st['median_min_no_penalty']:.0f} min", "is the median walk faced by the "
                                                       "worst-served of\nthat group — before "
                                                       "any slope penalty at all"),
        ]
        y = 0.74
        for big, cap in headline:
            fig.text(0.08, y, big, fontsize=30, fontweight="bold", color=INK)
            fig.text(0.34, y + 0.018, cap, fontsize=10, va="top", color="#444",
                     linespacing=1.5)
            y -= 0.115

        _para(fig, 0.26,
              f"Scope   {S['n_facilities']} library locations · "
              f"{d['land'].sum() * 0.0225:,.0f} km² analysed · "
              f"{S['population']:,.0f} residents\n"
              f"Terrain  elevation {S['elev_range'][0]:.0f}–{S['elev_range'][1]:.0f} m · "
              f"{S['grade_steep_pct']:.1f}% of walk segments steeper than 8.33%\n"
              f"Standard 15-minute neighbourhood goal; 3 mph on the flat = 0.75 mi\n"
              f"Sources  OpenStreetMap walk network · US Census ACS 5-year 2023 · "
              f"USGS 3DEP elevation", size=10)
        _footer(fig, city, 1); pdf.savefig(fig); plt.close(fig)

        # ---------------------------------------------------------------- page 2
        fig = plt.figure(figsize=PAGE)
        _title(fig, "Where the walk is long",
               "Travel time to the nearest library, on foot, accounting for slope")
        ax = fig.add_axes([0.08, 0.30, 0.84, 0.575])
        im = _map(ax, s, t15, "", cmap="magma_r", vmax=40)
        cb = fig.colorbar(im, ax=ax, shrink=0.62, pad=0.02)
        cb.set_label("minutes to nearest library (adult, 3 mph flat)", fontsize=9)
        _para(fig, 0.25,
              f"Median walk is {np.nanmedian(t15[d['inhabited']]):.0f} minutes. "
              f"Blue dots are the {S['n_facilities']} branches. Darker areas are further "
              f"in time, not distance — a\nsteep half-mile costs more than a flat one. "
              f"Areas outside the analysed land mask (open water,\n"
              f"and cells more than 250 m from any mapped pedestrian way) are blank.")
        _footer(fig, city, 2); pdf.savefig(fig); plt.close(fig)

        # ---------------------------------------------------------------- page 3
        fig = plt.figure(figsize=PAGE)
        _title(fig, "A time standard is not one distance",
               "The same policy sentence describes a different city for each kind of walker")
        ax = fig.add_axes([0.30, 0.50, 0.62, 0.36])
        yy = np.arange(len(PROFILES))
        for i, mins in enumerate(TIME_BUDGETS_MIN):
            vals = [r[mins]["pct"] for r in S["profiles"]]
            labs = [f"{r[mins]['beyond']:,.0f}" for r in S["profiles"]]
            bars = ax.barh(yy + (i - 0.5) * 0.36, vals, height=0.36,
                           color=["#e4572e", "#f5b841"][i], edgecolor="black", lw=0.6,
                           label=f"{mins} min")
            for b, l in zip(bars, labs):
                ax.text(b.get_width() - 1.5, b.get_y() + b.get_height() / 2, l,
                        va="center", ha="right", fontsize=8, fontweight="bold")
        ax.set_yticks(yy)
        ax.set_yticklabels([f"{p.label}\n{p.speed_mps:.2f} m/s" for p in PROFILES],
                           fontsize=8.5)
        ax.invert_yaxis(); ax.set_xlim(0, 100)
        ax.set_xlabel("% of that group beyond the standard", fontsize=9)
        ax.grid(axis="x", alpha=0.25); ax.set_axisbelow(True)
        ax.legend(fontsize=8, loc="lower right")

        rows = [("profile", "group", "10 min", "15 min", "no route")]
        for r in S["profiles"]:
            rows.append((r["profile"].label[:26], f"{r[15]['total']:,.0f}",
                         f"{r[10]['beyond']:,.0f} ({r[10]['pct']:.0f}%)",
                         f"{r[15]['beyond']:,.0f} ({r[15]['pct']:.0f}%)",
                         f"{r[15]['unreachable']:,.0f}"))
        tax = fig.add_axes([0.08, 0.28, 0.84, 0.15]); tax.axis("off")
        tb = tax.table(cellText=rows[1:], colLabels=rows[0], loc="center",
                       cellLoc="right", colLoc="right",
                       colWidths=[0.30, 0.15, 0.19, 0.19, 0.14])
        tb.auto_set_font_size(False); tb.set_fontsize(8); tb.scale(1, 1.6)
        for i in range(1, len(rows)):
            tb[i, 0].set_text_props(ha="left")
        for j in range(len(rows[0])):
            tb[0, j].set_facecolor("#eee"); tb[0, j].set_text_props(fontweight="bold")
        _para(fig, 0.24,
              "Each row is measured against its own population, not a share of the city. "
              "Walking speeds are\nplanning defaults: 3 mph adult, 1.00 m/s for 65+, "
              "0.80 m/s with an ambulatory difficulty.")
        _footer(fig, city, 3); pdf.savefig(fig); plt.close(fig)

        # ---------------------------------------------------------------- page 4
        fig = plt.figure(figsize=PAGE)
        _title(fig, "Slope, and who it excludes",
               "Grade excludes people that distance alone does not, and the effect "
               "is concentrated")
        tm = d["time_mobility"] / 60.0
        unreach = d["land"] & ~np.isfinite(d["time_mobility"])
        ax = fig.add_axes([0.08, 0.34, 0.84, 0.53])
        im = _map(ax, s, tm, "", cmap="magma_r", vmax=60, unreachable=unreach)
        cb = fig.colorbar(im, ax=ax, shrink=0.62, pad=0.02)
        cb.set_label("minutes at 0.80 m/s, ADA-compliant routes only", fontsize=9)
        mob = S["profiles"][2][15]
        st = stranded_profile(city_key)
        _para(fig, 0.285,
              f"Cyan marks land with no ADA-compliant walking route to any library: "
              f"{st['count']:,.0f} residents with an\nambulatory difficulty, "
              f"{100 * st['count'] / mob['total']:.0f}% of that group. "
              f"{S['grade_steep_pct']:.1f}% of walk segments exceed the 8.33% limit.\n\n"
              f"That count is sensitive to the threshold — it ranges "
              f"{st['range'][0]:,.0f}–{st['range'][1]:,.0f} between a 1:20 and a 1:8 "
              f"cutoff — so it\nshould not be read as a precise figure. The finding "
              f"underneath it is not sensitive. These are\nremote locations before slope "
              f"is considered at all: with no slope penalty whatsoever the same\n"
              f"cohort still faces a median {st['median_min_no_penalty']:.0f}-minute walk, "
              f"and {st['pct_over_60_no_penalty']:.0f}% of them over an hour. Slope is a "
              f"second\neffect on top of an already severe access deficit, and it falls "
              f"almost wholly on wheelchair users.")
        _footer(fig, city, 4); pdf.savefig(fig); plt.close(fig)

        # ---------------------------------------------------------------- page 5
        R = bench_results(city_key, k=k)
        sb, cov = R["s"], R["cov"]
        base_cov = ((bench_field(sb, d["fac_nodes"]) <= R["standard"])
                    & d["inhabited"]).ravel()
        popflat = np.where(d["inhabited"].ravel(), d["population"].ravel(), 0.0)
        gain_all = (cov & ~base_cov) @ popflat

        fig = plt.figure(figsize=PAGE)
        _title(fig, "Underserved pockets and best sites",
               "Contiguous residential areas beyond a 15-minute walk, ranked by "
               "residents affected")
        # Pockets are cut over habitable land only. Including parks, port terminals and
        # airfields would shade land nobody lives on and -- since such places are by
        # construction far from everything -- place the marker in the middle of one.
        lab, n = ndimage.label((t15 > 15) & d["habitable"],
                               structure=ndimage.generate_binary_structure(2, 1))
        pk = []
        for i in range(1, n + 1):
            reg = lab == i
            if reg.sum() < 2:
                continue
            # Marker = the candidate site inside this pocket that would bring the most
            # residents within the standard, not the pocket's worst-served point. The
            # worst-served point is systematically the emptiest corner of the pocket.
            inpocket = np.array([bool(reg[r, c]) for r, c in sb["cand_rc"]])
            if inpocket.any():
                gi = np.where(inpocket, gain_all, -1.0)
                bi = int(np.argmax(gi))
                mr, mc = sb["cand_rc"][bi]
                gain, xy = float(gain_all[bi]), (d["xs"][mc], d["ys"][mr])
            else:
                mm = np.where(reg, t15, -np.inf)
                r0, c0 = np.unravel_index(np.argmax(mm), mm.shape)
                gain, xy = 0.0, (d["xs"][c0], d["ys"][r0])
            pk.append({"pop": float(d["population"][reg].sum()), "reg": reg,
                       "km2": reg.sum() * 0.0225, "worst": float(t15[reg].max()),
                       "nocar": float(d["no_vehicle_hh"][reg].sum()),
                       "gain": gain, "xy": xy})
        pk.sort(key=lambda x: -x["pop"])

        dens = np.where(d["habitable"] & (d["population_density"] > 0),
                        d["population_density"], np.nan)
        ax = fig.add_axes([0.08, 0.36, 0.84, 0.51])
        xs, ys = d["xs"], d["ys"]
        ax.imshow(dens, origin="lower", extent=[xs[0], xs[-1], ys[0], ys[-1]],
                  cmap="Greys", norm=LogNorm(vmin=200, vmax=np.nanmax(dens)),
                  interpolation="nearest")
        ov = np.zeros(dens.shape, dtype=bool)
        for p in pk:
            ov |= p["reg"]
        ax.imshow(np.where(ov, 1.0, np.nan), origin="lower",
                  extent=[xs[0], xs[-1], ys[0], ys[-1]], cmap="autumn_r",
                  alpha=0.5, vmin=0, vmax=1.6, interpolation="nearest")
        fac = gpd.read_file(DATA / f"{city.key}_facilities.geojson").to_crs(city.crs)
        ax.scatter(fac.geometry.x, fac.geometry.y, s=34, c="#00d4ff", marker="o",
                   edgecolor="white", lw=0.8, zorder=4)
        for i, p in enumerate(pk[:5], 1):
            ax.annotate(f"{i}", p["xy"], fontsize=9, fontweight="bold", ha="center",
                        bbox=dict(boxstyle="circle,pad=0.24", fc="#ffe680", ec="black",
                                  lw=0.8), zorder=6)
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_color("#bbb")

        rows = [("#", "residents", "car-free HH", "area", "worst walk", "site gains")]
        for i, p in enumerate(pk[:6], 1):
            rows.append((str(i), f"{p['pop']:,.0f}", f"{p['nocar']:,.0f}",
                         f"{p['km2']:.1f} km²", f"{p['worst']:.0f} min",
                         f"{p['gain']:,.0f}"))
        tax = fig.add_axes([0.08, 0.15, 0.84, 0.17]); tax.axis("off")
        tb = tax.table(cellText=rows[1:], colLabels=rows[0], loc="center",
                       cellLoc="right", colWidths=[0.09, 0.20, 0.19, 0.17, 0.18, 0.17])
        tb.auto_set_font_size(False); tb.set_fontsize(8.5); tb.scale(1, 1.6)
        for j in range(len(rows[0])):
            tb[0, j].set_facecolor("#eee"); tb[0, j].set_text_props(fontweight="bold")
        _para(fig, 0.115,
              "Numbered markers are the best available branch site inside each pocket — "
              "the location that\nbrings the most residents within 15 minutes — chosen "
              "from habitable land only, so parks,\nport terminals and airfields are "
              "never proposed.")
        _footer(fig, city, 5); pdf.savefig(fig); plt.close(fig)

        # ---------------------------------------------------------------- page 6
        fig = plt.figure(figsize=PAGE)
        _title(fig, f"Where should the next {k} branches go?",
               "Siting strategies scored on residents brought within 15 minutes")
        names = list(R["rows"])
        gains = [R["rows"][nm]["covered"] - R["base"]["covered"] for nm in names]
        order = np.argsort(gains)[::-1]
        ax = fig.add_axes([0.36, 0.55, 0.56, 0.30])
        bars = ax.barh(range(len(names)), [gains[i] for i in order],
                       color=["#2a9d8f" if names[i].startswith("MCLP") else "#bbb"
                              for i in order], edgecolor="black", lw=0.6)
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels([names[i] for i in order], fontsize=8.5)
        ax.invert_yaxis()
        ax.set_xlabel("additional residents within a 15-minute walk", fontsize=9)
        ax.grid(axis="x", alpha=0.25); ax.set_axisbelow(True)
        for b, i in zip(bars, order):
            ax.text(b.get_width() * 1.01, b.get_y() + b.get_height() / 2,
                    f"+{gains[i]:,.0f}", va="center", fontsize=8, fontweight="bold")
        best = max(gains)
        _para(fig, 0.50,
              f"Greedy maximal-covering location (MCLP) adds {best:,.0f} residents with "
              f"{k} branches, raising\ncoverage from {covered_pct:.0f}% to "
              f"{covered_pct + 100 * best / S['population']:.0f}%. It is scored here "
              f"against topological and trivial alternatives;\nsee the repository for the "
              f"full comparison. Candidate sites are inhabited cells on a 450 m grid.")
        _para(fig, 0.36, "Method and caveats", size=12, weight="bold")
        _para(fig, 0.325,
              "Walk network from OpenStreetMap, retaining all connected components. "
              "Travel time uses Tobler's\nhiking function renormalised to each profile's "
              "flat speed; the mobility profile additionally treats\nsegments steeper "
              "than 8.33% as impassable. Population is ACS 2023 block-group data "
              "rasterised to\na 150 m grid; poverty, vehicle access and ambulatory "
              "difficulty are tract-level and therefore coarser.\n\n"
              "Known limits: sidewalk quality, curb ramps, crossing delay and transit are "
              "not modelled, so the\nmobility figures remain optimistic even with slope. "
              "Walking speeds are literature defaults rather\nthan locally observed. "
              "Travel time is one-way; a downhill outbound trip is uphill on return.\n"
              "Facility sets are branch locations only and take no account of opening "
              "hours or capacity.")
        _footer(fig, city, 6); pdf.savefig(fig); plt.close(fig)

    return path


if __name__ == "__main__":
    import sys

    for c in sys.argv[1:] or ["seattle", "tacoma"]:
        print(build_report(c))
