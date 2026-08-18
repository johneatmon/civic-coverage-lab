"""Re-derive every figure in README.md's 'Current results' section from a fresh build.

The phase log below that section is a changelog and is deliberately not checked: its
numbers record what was true when each phase ran, several under models later corrected.
"""

import numpy as np
from scipy import ndimage, stats
from scipy.sparse import csr_matrix

from ccl.bench import CONN4, field_from, random_picks, results, score
from ccl.build import load
from ccl.cities import PROFILES, distance_m, get
from ccl.ladder import rungs
from ccl.sensitivity import stranded_profile
from ccl.standards import summary

CITIES = ["seattle", "tacoma", "phoenix"]
ok = fail = 0


def chk(label, claim, got, tol=0.0):
    global ok, fail
    good = abs(claim - got) <= max(tol, abs(got) * 0.005)
    print(f"  {'OK ' if good else 'XX '} {label:46s} claim {claim:>12,.2f}  got {got:>12,.2f}")
    ok += good
    fail += not good


D = {c: load(c) for c in CITIES}
R = {c: results(c, k=8) for c in CITIES}

print("ACCESS TABLE")
for c, br, pop, rpb, med in [("seattle", 28, 722212, 25793, 19),
                             ("tacoma", 8, 212330, 26541, 26),
                             ("phoenix", 17, 1539333, 90549, 53)]:
    d, m = D[c], D[c]["land"]
    chk(f"branches {c}", br, int(d["fac_nodes"].size))
    chk(f"population {c}", pop, d["population"][m].sum(), 2)
    chk(f"residents per branch {c}", rpb, d["population"][m].sum() / int(d["fac_nodes"].size), 2)
    chk(f"median walk {c}", med, np.median(d["time_adult"][d["inhabited"]] / 60.0), 0.5)

pcts = {"seattle": (57.5, 75.0, 92.9), "tacoma": (79.7, 89.6, 95.6),
        "phoenix": (95.1, 97.4, 98.5)}
for c in CITIES:
    d, m = D[c], D[c]["land"]
    for p, cl in zip(PROFILES, pcts[c]):
        tot = d[p.pop_field][m].sum()
        chk(f"{p.key} beyond 15 min {c}", cl,
            100 * d[p.pop_field][m & ~(d[f"time_{p.key}"] <= 900)].sum() / tot, 0.05)

print("\nLADDER")
lad = {"seattle": (35.8, 55.5, 57.5, 92.9, 21.7, 156927),
       "tacoma": (62.9, 79.4, 79.7, 95.6, 16.8, 35765),
       "phoenix": (90.0, 95.1, 95.1, 98.5, 5.1, 78977)}
for c in CITIES:
    rs = rungs(c)
    for i in range(4):
        chk(f"rung {i + 1} {c}", lad[c][i], rs[i]["pct"], 0.05)
    chk(f"understates pts {c}", lad[c][4], rs[2]["pct"] - rs[0]["pct"], 0.05)
    chk(f"understates people {c}", lad[c][5], rs[2]["n"] - rs[0]["n"], 5)

print("\nTERRAIN / CAR ACCESS")
terr = {"seattle": (24.5, 12288, 45), "tacoma": (14.0, 3284, 23), "phoenix": (1.9, 1066, 1)}
car = {"seattle": (38.3, 58.6), "tacoma": (72.3, 80.2), "phoenix": (92.4, 94.8)}
det = {"seattle": 1.32, "tacoma": 1.35, "phoenix": 1.34}
for c in CITIES:
    d, m = D[c], D[c]["land"]
    eic = d["edge_in_city"]
    chk(f"steep >5% {c}", terr[c][0],
        100 * float((np.abs(d["edge_grade"][eic]) > 0.05).mean()), 0.05)
    st = stranded_profile(c)
    chk(f"no route within 5% {c}", terr[c][1], st["count"], 3)
    chk(f"  as pct of group {c}", terr[c][2],
        100 * st["count"] / d["pop_ambulatory"][m].sum(), 0.5)
    beyond = m & ~(d["time_adult"] <= 900)
    hh, nv = d["households"], d["no_vehicle_hh"]
    chk(f"car-free underserved {c}", car[c][0], 100 * nv[beyond].sum() / nv[m].sum(), 0.05)
    chk(f"car-owning underserved {c}", car[c][1],
        100 * (hh[beyond].sum() - nv[beyond].sum()) / (hh[m].sum() - nv[m].sum()), 0.05)
    mm = m & np.isfinite(d["network"]) & np.isfinite(d["euclidean"])
    r = d["network"][mm] / np.maximum(d["euclidean"][mm], 1)
    w = d["population"][mm]
    o = np.argsort(r)
    chk(f"median detour {c}", det[c], r[o][np.searchsorted(np.cumsum(w[o]) / w.sum(), 0.5)], 0.005)
chk("Seattle threshold range low", 846, stranded_profile("seattle")["range"][0], 3)
chk("Seattle threshold range high", 18603, stranded_profile("seattle")["range"][1], 3)
chk("Seattle median walk, no penalty", 41, stranded_profile("seattle")["median_min_no_penalty"], 0.5)

print("\nSITING BENCHMARK")
bench = {"MCLP greedy": [87779, 52626, 86538], "PH by persistence": [25014, 8624, 8508],
         "PH by population": [16437, 16366, 1003],
         "worst-point (no topology)": [4627, 6907, 970]}
for nm, vals in bench.items():
    for c, v in zip(CITIES, vals):
        chk(f"{nm[:22]} {c}", v, R[c]["rows"][nm]["covered"] - R[c]["base"]["covered"], 1)

rnd = {"seattle": 33301, "tacoma": 21521, "phoenix": 27816}
pct = {"seattle": (10.0, 0.0), "tacoma": (0.0, 10.0), "phoenix": (0.0, 0.0)}
corr = {"seattle": 0.01, "tacoma": -0.16, "phoenix": -0.27}
med_g = {"seattle": 3559, "tacoma": 2645, "phoenix": 2826}
wp_g = {"seattle": 407, "tacoma": 907, "phoenix": 117}
share = {"seattle": 40.6, "tacoma": 90.4, "phoenix": 98.3}
for c in CITIES:
    s, d, cov, std = R[c]["s"], D[c], R[c]["cov"], R[c]["standard"]
    base_cov = R[c]["base"]["covered"]
    dr = np.array([score(s, random_picks(s, 8, sd), std)["covered"] - base_cov
                   for sd in range(30)])
    chk(f"random mean {c}", rnd[c], dr.mean(), 1)
    for nm, cl in zip(["PH by persistence", "PH by population"], pct[c]):
        chk(f"{nm[:17]} pctile {c}", cl,
            100 * (dr < R[c]["rows"][nm]["covered"] - base_cov).mean(), 0.1)
    bf = field_from(s, d["fac_nodes"])
    done = ((bf <= std) & d["inhabited"]).ravel()
    pf = np.where(d["inhabited"].ravel(), d["population"].ravel(), 0.0)
    gain = (cov & ~done) @ pf
    rem = np.array([bf[r, cc] for r, cc in s["cand_rc"]]) / 60.0
    msk = np.isfinite(rem) & np.isfinite(gain)
    chk(f"pearson {c}", corr[c], stats.pearsonr(rem[msk], gain[msk]).statistic, 0.005)
    chk(f"median candidate gain {c}", med_g[c], np.median(gain[msk]), 1)
    chk(f"worst-point gain {c}", wp_g[c],
        np.median(gain[R[c]["picks"]["worst-point (no topology)"]]), 1)
    lab, n = ndimage.label((bf > std) & d["land"], structure=CONN4)
    pops = np.array(sorted([d["population"][lab == i].sum() for i in range(1, n + 1)])[::-1])
    chk(f"largest pocket share {c}", share[c], 100 * pops[0] / pops.sum(), 0.1)

print("\nPARKS (second amenity)")
import geopandas as gpd
from ccl.build import DATA as _D
park = {"seattle": (254, 19.6, 33.8, 71.5, 9576), "tacoma": (66, 40.7, 60.2, 76.0, 2502)}
grade = {"seattle": (3.9, 3.0, 4.6), "tacoma": (2.5, 2.6, 2.8)}
for c, (nf, pa, po, pm, nr) in park.items():
    Sp = summary(c, "parks")
    chk(f"park count {c}", nf, Sp["n_facilities"])
    for p_, cl in zip(PROFILES, (pa, po, pm)):
        chk(f"parks {p_.key} beyond 10 min {c}", cl, Sp["profiles"][PROFILES.index(p_)][10]["pct"], 0.05)
    chk(f"parks no route {c}", nr, Sp["profiles"][2][10]["unreachable"], 3)
    dd = D[c]
    csr_ = csr_matrix((dd["csr_data"], dd["csr_indices"], dd["csr_indptr"]),
                      shape=tuple(dd["csr_shape"]))
    coo_ = csr_.tocoo(); g_ = np.abs(dd["edge_grade"]); nxy = dd["node_xy"]
    eic_ = dd["edge_in_city"]
    chk(f"city-wide mean grade {c}", grade[c][0], g_[eic_].mean() * 100, 0.05)
    cty = get(c)
    for i, am_ in enumerate(("libraries", "parks"), start=1):
        fac = gpd.read_file(_D / f"{c}_{am_}.geojson").to_crs(cty.crs)
        nodes = gpd.GeoDataFrame(geometry=gpd.points_from_xy(nxy[:, 0], nxy[:, 1]), crs=cty.crs)
        buf = gpd.GeoDataFrame(geometry=fac.geometry.buffer(150), crs=cty.crs)
        hit = np.zeros(len(nxy), dtype=bool)
        hit[gpd.sjoin(nodes, buf, how="inner", predicate="within").index.unique().to_numpy()] = True
        chk(f"mean grade near {am_} {c}", grade[c][i],
            g_[hit[coo_.row] & eic_].mean() * 100, 0.05)

print(f"\n{'=' * 76}\n  {ok} verified, {fail} MISMATCHED\n{'=' * 76}")
