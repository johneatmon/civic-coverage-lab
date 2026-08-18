import numpy as np
from scipy import ndimage, stats
from ccl.bench import results, score, random_picks, field_from, CONN4
from ccl.build import load
from ccl.cities import PROFILES, distance_m
from ccl.ladder import rungs
from ccl.sensitivity import stranded_profile

CITIES = ["seattle", "tacoma", "phoenix"]
ok = fail = 0
def chk(label, claim, got, tol=0.0):
    global ok, fail
    good = abs(claim - got) <= max(tol, abs(got) * 0.005)
    print(f"  {'OK ' if good else 'XX '} {label:44s} claim {claim:>12,.2f}  got {got:>12,.2f}")
    globals().__setitem__('ok', ok + good); globals().__setitem__('fail', fail + (not good))

R = {c: results(c, k=8) for c in CITIES}
D = {c: load(c) for c in CITIES}

print("BENCHMARK TABLE")
claims = {
 "MCLP greedy": [84183, 50304, 86538],
 "PH by persistence": [23096, 9333, 12462],
 "PH by population": [16409, 22563, 7283],
 "worst-point (no topology)": [5139, 6507, 4722],
}
for nm, vals in claims.items():
    for c, v in zip(CITIES, vals):
        chk(f"{nm[:20]} {c}", v, R[c]["rows"][nm]["covered"] - R[c]["base"]["covered"], 1)

print("\nRANDOM: 30 draws (mean, and % of draws each PH beats)")
rand_claims = {"seattle": 33845, "tacoma": 21918, "phoenix": 24453}
pct_claims = {"seattle": (6.7, 0.0), "tacoma": (0.0, 63.3), "phoenix": (0.0, 0.0)}
best_seattle = None
for c in CITIES:
    s, std, base = R[c]["s"], R[c]["standard"], R[c]["base"]["covered"]
    dr = np.array([score(s, random_picks(s, 8, sd), std)["covered"] - base for sd in range(30)])
    if c == "seattle": best_seattle = dr.max()
    chk(f"random mean {c}", rand_claims[c], dr.mean(), 1)
    for nm, cl in zip(["PH by persistence", "PH by population"], pct_claims[c]):
        v = R[c]["rows"][nm]["covered"] - base
        chk(f"{nm[:17]} pctile {c}", cl, 100.0 * (dr < v).mean(), 0.1)
chk("Seattle best of 30 random draws", 49921, best_seattle, 1)

print("\nMECHANISM: correlations, median gains, worst-point gain")
corr = {"seattle": (0.02, 0.19), "tacoma": (-0.13, -0.02), "phoenix": (-0.26, -0.25)}
med = {"seattle": 3575, "tacoma": 2699, "phoenix": 2847}
wp = {"seattle": 477, "tacoma": 66, "phoenix": 91}
for c in CITIES:
    s, d, cov, std = R[c]["s"], D[c], R[c]["cov"], R[c]["standard"]
    base = field_from(s, d["fac_nodes"])
    done = ((base <= std) & d["inhabited"]).ravel()
    pf = np.where(d["inhabited"].ravel(), d["population"].ravel(), 0.0)
    gain = (cov & ~done) @ pf
    rem = np.array([base[r, cc] for r, cc in s["cand_rc"]]) / 60.0
    m = np.isfinite(rem) & np.isfinite(gain)
    chk(f"pearson {c}", corr[c][0], stats.pearsonr(rem[m], gain[m]).statistic, 0.005)
    chk(f"spearman {c}", corr[c][1], stats.spearmanr(rem[m], gain[m]).statistic, 0.005)
    chk(f"median candidate gain {c}", med[c], np.median(gain[m]), 1)
    chk(f"worst-point site gain {c}", wp[c],
        np.median(gain[R[c]["picks"]["worst-point (no topology)"]]), 1)

print("\nPOCKET STRUCTURE")
shares = {"seattle": 40.6, "tacoma": 90.8, "phoenix": 98.4}
for c in CITIES:
    s, d, std = R[c]["s"], D[c], R[c]["standard"]
    base = field_from(s, d["fac_nodes"])
    lab, n = ndimage.label((base > std) & d["land"], structure=CONN4)
    pops = np.array(sorted([d["population"][lab == i].sum() for i in range(1, n+1)])[::-1])
    chk(f"largest pocket share {c}", shares[c], 100*pops[0]/pops.sum(), 0.1)
    if c == "seattle":
        for nm, cl in [("PH by persistence", 67639), ("PH by population", 168663)]:
            rc = s["cand_rc"][R[c]["picks"][nm]]
            pp = np.array([0.0] + [d["population"][lab == i].sum() for i in range(1, n+1)])
            chk(f"median pocket pop {nm[6:]}", cl,
                np.median([pp[lab[r, cc]] for r, cc in rc]), 1)

print("\nLADDER (Seattle)")
rs = rungs("seattle")
for i, cl in enumerate([35.8, 55.4, 57.5, 93.2]):
    chk(f"rung {i+1} pct", cl, rs[i]["pct"], 0.05)
chk("network step pp", 19.7, rs[1]["pct"]-rs[0]["pct"], 0.05)
chk("terrain step pp", 1.93, rs[2]["pct"]-rs[1]["pct"], 0.05)
chk("radius understates, points", 21.7, rs[2]["pct"]-rs[0]["pct"], 0.05)
chk("radius understates, people", 155907, rs[2]["n"]-rs[0]["n"], 5)

print("\nPROFILES + SLOPE + GRADE EXCLUSION (Seattle)")
d = D["seattle"]; m = d["land"]
for p, cl in zip(PROFILES, [1206, 900, 720]):
    chk(f"{p.key} 15-min distance m", cl, distance_m(p, 15), 1)
for p, cl in zip(PROFILES, [57.5, 75.0, 93.2]):
    tot = d[p.pop_field][m].sum()
    chk(f"{p.key} beyond 15 min pct", cl,
        100*d[p.pop_field][m & ~(d[f'time_{p.key}'] <= 900)].sum()/tot, 0.05)
adult, mob = PROFILES[0], PROFILES[2]
for p, cl in [(adult, 1.93), (mob, 13.03)]:
    tot = d[p.pop_field][m].sum()
    with_s = 100*d[p.pop_field][m & ~(d[f'time_{p.key}'] <= 900)].sum()/tot
    flat = 100*d[p.pop_field][m & (d["network"] > distance_m(p, 15))].sum()/tot
    chk(f"slope cost {p.key} (pp)", cl, with_s - flat, 0.3)
st = stranded_profile("seattle")
chk("no route within 5% grade", 12484, st["count"], 5)
chk("  as pct of group", 46.0, 100*st["count"]/d["pop_ambulatory"][m].sum(), 0.5)
chk("threshold range low", 1057, st["range"][0], 5)
chk("threshold range high", 19775, st["range"][1], 5)
chk("median walk, no slope penalty", 41, st["median_min_no_penalty"], 0.5)
chk("pct over 60 min, no penalty", 10, st["pct_over_60_no_penalty"], 0.6)

print("\nDETOUR RATIOS")
for c, cl in [("seattle", 1.32), ("phoenix", 1.35)]:
    d = D[c]; mm = d["land"] & np.isfinite(d["network"]) & np.isfinite(d["euclidean"])
    r = d["network"][mm]/np.maximum(d["euclidean"][mm], 1)
    w = d["population"][mm]; o = np.argsort(r)
    cw = np.cumsum(w[o])/w.sum()
    chk(f"median detour {c}", cl, r[o][np.searchsorted(cw, 0.5)], 0.005)

print(f"\n{'=' * 72}\n  {ok} verified, {fail} MISMATCHED\n{'=' * 72}")
