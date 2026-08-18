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
for c, br, pop, rpb, med in [("seattle", 28, 721942, 25784, 19),
                             ("tacoma", 8, 210290, 26286, 26),
                             ("phoenix", 17, 1522291, 89547, 53)]:
    d, m = D[c], D[c]["land"]
    chk(f"branches {c}", br, int(d["fac_nodes"].size))
    chk(f"population {c}", pop, d["population"][m].sum(), 2)
    chk(f"residents per branch {c}", rpb, d["population"][m].sum() / int(d["fac_nodes"].size), 2)
    chk(f"median walk {c}", med, np.median(d["time_adult"][d["inhabited"]] / 60.0), 0.5)

pcts = {"seattle": (57.5, 75.0, 93.2), "tacoma": (79.5, 89.5, 95.4),
        "phoenix": (95.0, 97.4, 98.5)}
for c in CITIES:
    d, m = D[c], D[c]["land"]
    for p, cl in zip(PROFILES, pcts[c]):
        tot = d[p.pop_field][m].sum()
        chk(f"{p.key} beyond 15 min {c}", cl,
            100 * d[p.pop_field][m & ~(d[f"time_{p.key}"] <= 900)].sum() / tot, 0.05)

print("\nLADDER")
lad = {"seattle": (35.8, 55.4, 57.5, 93.2, 21.7, 155907),
       "tacoma": (62.5, 79.2, 79.5, 95.4, 17.0, 35775),
       "phoenix": (89.9, 95.0, 95.0, 98.5, 5.2, 78795)}
for c in CITIES:
    rs = rungs(c)
    for i in range(4):
        chk(f"rung {i + 1} {c}", lad[c][i], rs[i]["pct"], 0.05)
    chk(f"understates pts {c}", lad[c][4], rs[2]["pct"] - rs[0]["pct"], 0.05)
    chk(f"understates people {c}", lad[c][5], rs[2]["n"] - rs[0]["n"], 5)

print("\nTERRAIN / CAR ACCESS")
terr = {"seattle": (24.6, 12484, 46), "tacoma": (14.4, 3087, 22), "phoenix": (1.9, 1063, 1.3)}
car = {"seattle": (38.1, 58.6), "tacoma": (72.1, 80.0), "phoenix": (92.4, 94.7)}
det = {"seattle": 1.32, "tacoma": 1.35, "phoenix": 1.35}
for c in CITIES:
    d, m = D[c], D[c]["land"]
    chk(f"steep >5% {c}", terr[c][0], 100 * float((np.abs(d["edge_grade"]) > 0.05).mean()), 0.05)
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
chk("Seattle threshold range low", 1057, stranded_profile("seattle")["range"][0], 3)
chk("Seattle threshold range high", 19775, stranded_profile("seattle")["range"][1], 3)
chk("Seattle median walk, no penalty", 41, stranded_profile("seattle")["median_min_no_penalty"], 0.5)

print("\nSITING BENCHMARK")
bench = {"MCLP greedy": [84183, 50304, 86538], "PH by persistence": [23096, 9333, 12462],
         "PH by population": [16409, 22563, 7283],
         "worst-point (no topology)": [5139, 6507, 4722]}
for nm, vals in bench.items():
    for c, v in zip(CITIES, vals):
        chk(f"{nm[:22]} {c}", v, R[c]["rows"][nm]["covered"] - R[c]["base"]["covered"], 1)

rnd = {"seattle": 33845, "tacoma": 21918, "phoenix": 24453}
pct = {"seattle": (6.7, 0.0), "tacoma": (0.0, 63.3), "phoenix": (0.0, 0.0)}
corr = {"seattle": 0.02, "tacoma": -0.13, "phoenix": -0.26}
med_g = {"seattle": 3575, "tacoma": 2699, "phoenix": 2847}
wp_g = {"seattle": 477, "tacoma": 66, "phoenix": 91}
share = {"seattle": 40.6, "tacoma": 90.8, "phoenix": 98.4}
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
park = {"seattle": (254, 19.6, 33.9, 72.2, 9566), "tacoma": (66, 40.4, 59.9, 76.3, 2512)}
grade = {"seattle": (3.9, 3.0, 4.7), "tacoma": (2.6, 2.6, 2.9)}
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
    chk(f"city-wide mean grade {c}", grade[c][0], g_.mean() * 100, 0.05)
    cty = get(c)
    for i, am_ in enumerate(("libraries", "parks"), start=1):
        fac = gpd.read_file(_D / f"{c}_{am_}.geojson").to_crs(cty.crs)
        nodes = gpd.GeoDataFrame(geometry=gpd.points_from_xy(nxy[:, 0], nxy[:, 1]), crs=cty.crs)
        buf = gpd.GeoDataFrame(geometry=fac.geometry.buffer(150), crs=cty.crs)
        hit = np.zeros(len(nxy), dtype=bool)
        hit[gpd.sjoin(nodes, buf, how="inner", predicate="within").index.unique().to_numpy()] = True
        chk(f"mean grade near {am_} {c}", grade[c][i], g_[hit[coo_.row]].mean() * 100, 0.05)

print(f"\n{'=' * 76}\n  {ok} verified, {fail} MISMATCHED\n{'=' * 76}")
