# I brought topology to a city planning problem and a 1974 algorithm beat it

There is a nice paper that uses persistent homology — topological data analysis — to find
holes in civic resource coverage. Instead of drawing a circle around each facility and
calling everything inside it "served", it looks at the structure of coverage across every
scale at once and reports the gaps that persist. I liked it enough to build on it.

So I did, on library access in Seattle, Tacoma and Phoenix. Topology found the holes. Then
I benchmarked it against classical operations research on the decision the holes are
supposed to inform — *where should the next branch go?* — and it could not beat random
guessing.

## The benchmark

Eight new branches, chosen from the same 833-site candidate grid, scored identically on
residents brought within a 15-minute walk:

| strategy | Seattle | Tacoma | Phoenix |
|---|---:|---:|---:|
| **Greedy MCLP** (Church & ReVelle, 1974) | **+87,779** | **+52,626** | **+86,538** |
| random placement (mean of 30 draws) | +33,301 | +21,521 | +27,816 |
| PH ranked by persistence | +25,014 | +8,624 | +8,508 |
| PH ranked by population | +16,437 | +16,366 | +1,003 |
| worst-served point (no topology) | +4,627 | +6,907 | +970 |

A single point estimate against random is a weak comparison, so here is each topological
strategy against the whole distribution of 30 random draws:

| | Seattle | Tacoma | Phoenix |
|---|---:|---:|---:|
| PH by persistence beats… | 10.0% of random draws | 0.0% | 0.0% |
| PH by population beats… | 0.0% | 10.0% | 0.0% |

Every one of the six lands below at least 90% of random draws. Meanwhile greedy MCLP falls
outside the random range entirely in all three cities — Seattle's best of 30 random draws
was +48,625 against MCLP's +87,779.

**Topological holes are a diagnostic, not an optimizer.**

## Why it loses

Persistence measures how deep a gap is, and marks its most remote point. The trouble is
that remoteness is a weak guide to how many people a branch would reach — and the specific
places these rules aim at are far worse than weak.

Across the candidate pool the correlation between a site's travel time from existing
branches and its marginal coverage gain is small and not even consistent in sign: **+0.01
in Seattle, −0.16 in Tacoma, −0.27 in Phoenix**.
Remoteness explains at most about 7% of the variance in gain anywhere, and in Seattle
essentially none.

The tail is where the damage is. A median candidate site gains 3,559 residents in Seattle,
2,645 in Tacoma, 2,826 in Phoenix. The site that the no-topology worst-point rule
selects — the most remote place in the city — gains **407, 907 and 117**. That is 11%, 34%
and 4% of a median site: consistently worse than the middle of the distribution, though
how much worse varies a lot by city.

So the mechanism is not "remoteness is anti-correlated with need". It is that the extreme
of a weakly-informative quantity is reliably unrepresentative. Random placement draws from
the middle of that distribution and does fine. Every distance-driven rule deliberately
draws from its emptiest corner.

### The counterintuitive part, and where it stops

In Seattle, weighting the holes by population made things *worse* (+16,437 against
+25,014). My first guess was that it selects small dense pockets with little room to gain.
The data says the opposite: it picks the **largest** pockets — median pocket population
168,663, against 67,639 for the persistence ranking.

The bug is subtler. Population ranks the *region*; the placement rule then still puts the
branch at the worst-served *point inside that region*. A larger region has a more extreme
extremum, so the weighting selects a better neighborhood and then a worse corner of it.
The population signal never survives the trip to the decision.

**That reasoning only applies to Seattle, and the reason is the interesting part.** Ranking
gaps by population means something only if there is more than one gap worth ranking. The
largest single pocket holds 40.6% of Seattle's underserved residents — but **90.4% of
Tacoma's and 98.3% of Phoenix's**. Where one mega-pocket contains nearly everyone, the
ranking returns the same pocket every time and the strategy collapses to "worst-served
point of the one big gap"; whatever the two PH variants score there is not measuring the
ranking at all.

Which is itself a finding about the method: population-weighting a topological gap ranking
only has purchase in cities whose underserved population is genuinely fragmented. In the
sprawl case it degenerates, and any comparison built on it is unstable.

## Where topology did earn its keep

Not in siting — in **characterizing who is excluded**.

The project's original claim was that each modeling step changes the answer. Here is the
ladder, same city, same branches, each rung measured more carefully:

| Seattle | measure | beyond a 15-min walk |
|---|---|---:|
| 1. Straight-line radius | 1,206 m as the crow flies | 35.8% |
| 2. + street network | 1,206 m along the walk graph | 55.5% (+19.7 pp) |
| 3. + terrain | 15 min at 3 mph, slope-adjusted | 57.5% (+2.1 pp) |
| 4. + mobility profile | 15 min at 0.80 m/s, 5% max grade | 92.9% |

**Straight-line coverage understates Seattle's underserved population by 21.7 points —
156,927 people.** That is the number a service-area map drawn with circles gets wrong.

The network step is the big one, and it is not about Seattle's hills. Phoenix — flat, and
famous for its grid — has a *higher* median detour ratio (1.35) than Seattle (1.32),
because a grid forces Manhattan travel at roughly 1.3× straight-line no matter how level
the ground. I had predicted the opposite, in writing, before running it.

### A time standard is not one distance

"Everyone within a 15-minute walk" sounds like one requirement. It is a different distance
for every kind of walker, and each distance applies to a different population:

| profile | speed | 15 min | Seattle beyond it |
|---|---:|---:|---:|
| Adult (planning standard) | 1.34 m/s | 1,206 m | 57.5% |
| Older adult (65+) | 1.00 m/s | 900 m | 75.0% |
| Ambulatory difficulty | 0.80 m/s | 720 m | **92.9%** |

Seattle meets its 15-minute goal for 43% of adults and 7% of residents with an ambulatory
difficulty. Same sentence in the comprehensive plan, two different cities.

Terrain is what separates those rows. Adding slope moves the adult figure about **2
points** and the ambulatory-difficulty figure **13**. Nearly the entire cost of Seattle's
topography is paid by one group.

### A finding that survives its own fragile number

Under the accessible-route grade — 1:20, or 5%, per the 2010 ADA Standards and PROWAG
R302.4.1 — **12,288 Seattle residents with an ambulatory difficulty have no route to any
library that stays within grade.** That is 45% of them.

That count is fragile. Move the threshold across its defensible range (4%–15%) and it
swings from 18,603 to 846. It should never be quoted alone.

Two things underneath it are not fragile. Replace the hard cutoff with a graded penalty
and nobody is stranded — but the same cohort still faces a **median 41-minute walk with no
slope penalty applied at all**, and 10% of them over an hour. These are remote places
before terrain is considered; grade compounds an existing deficit rather than inventing
one. And the burden stays concentrated on the same profile under every variant tested.

## What I got wrong along the way

Worth recording, because the corrections were more instructive than the plan:

- **8.33% is not the pedestrian grade limit.** It is the maximum for a *ramp*. An
  accessible route is capped at 5%; steeper *is* a ramp and picks up handrails, landings
  and rise limits. Using 8.33% understated the excluded population threefold. It also
  means "no ADA-compliant route" was wrong on its own terms — PROWAG lets a sidewalk match
  a steep adjacent street, so steep sidewalks can be compliant.
- **Barriers are not what makes network distance matter.** Phoenix refuted that.
- **Block-group density puts people in parks.** The first version proposed a branch in the
  middle of Point Defiance Park and another in the Port of Tacoma tideflats, because
  spreading population evenly across a block group invents residents in its 275-hectare
  park — and a park, being far from everything, then wins the "worst-served point" marker.
  Population is now allocated onto habitable land only.
- **`osmnx.graph_from_polygon` keeps only the largest connected component by default.**
  Seattle's walk network is not connected. The default silently deleted West Seattle,
  including five library branches.

## The finding that needed a second amenity

Libraries were the case study; the pipeline takes a `(city, amenity)` pair. Running parks —
against the 10-minute standard Metro Parks Tacoma actually adopted — produced the result I
did not expect.

Parks are much better distributed. Under a fifth of Seattle adults are beyond a 10-minute
walk to one, against well over half for a 15-minute walk to a library. But **the gap between
an able-bodied adult and someone with an ambulatory difficulty is wider for parks, not
narrower**: 53 points against 36.

The reason is in the land:

| mean walk-segment grade | city-wide | near libraries | near parks |
|---|---:|---:|---:|
| Seattle | 3.9% | **3.0%** | **4.6%** |
| Tacoma | 2.5% | 2.6% | 2.8% |

A library is a building and buildings go where building is cheap, so branches sit on land
flatter than the city average. Parkland is largely what was left over — ravines, greenbelts,
bluffs, the slopes nobody could develop. The amenity that looks most equitably distributed
when you count facilities is the least equitable once you account for who is walking.

The effect is strong in Seattle and weak in Tacoma, which is what the mechanism predicts —
it needs terrain to bite.

Tacoma parks also gave the project its only external check. Metro Parks Tacoma publishes its
own 10-minute walkshed, so I ran their 72-park analysis set against their own standard. Their
published walkshed is 89.4 km²; a straight-line 804 m buffer of those parks is 88.6 km², a
0.9% match, while no network construction comes within 26 km². **Their published figure is a
crow-flies buffer**, and against network distance with terrain it overstates park access by
21 points for adults and 28 for residents with an ambulatory difficulty. Straight-line
buffers are standard practice rather than an error — that is exactly rung 1 of the ladder —
but it is the difference between 80.6% and 59.6% of a city.

Getting there required one real modeling change: a park is a polygon you enter at its edge,
so access nodes are every network node inside it or within 25 m, not a centroid. For Point
Defiance a centroid would have sat 800 m from any way in — the same error that, in an
earlier version, had the tool proposing a new library in the middle of that park.

## What this is not

[UW's Taskar Center](https://tcat.cs.washington.edu/) has been doing pedestrian
accessibility properly for years — AccessMap for routing, and **Walkshed** for exactly this
kind of planner-facing amenity analysis. Crucially, Walkshed runs on
[OS-CONNECT](https://www.washington.edu/news/2025/03/25/os-connect-accessmap-accessible-sidewalks/),
a statewide sidewalk network with curb ramps and crossings. On network fidelity for
Washington they win outright, and anything built on street centerlines — including this —
is a proxy by comparison.

What is different here: the per-profile decomposition with its own population denominators,
the siting-strategy benchmark, and portability. OS-CONNECT is Washington-only; this
pipeline ran Phoenix from the same code by changing a UTM zone and a county FIPS.

The obvious v2 is to swap the OSM centerline network for OS-CONNECT in Washington, which
would replace the largest single caveat — sidewalk quality, curb ramps and crossings are
entirely unmodelled, and every one of those omissions pushes the mobility numbers the same
way: optimistic.

## Reproducing it

```bash
uv run python -m ccl.build seattle tacoma phoenix
uv run python -m ccl.report seattle tacoma phoenix
```

Eight pages per city. Public data only: OpenStreetMap, Census ACS and TIGER, USGS 3DEP,
municipal open data.

---

Every figure above is re-derived from a fresh run by
[`scripts/verify_writeup.py`](scripts/verify_writeup.py) — 63 assertions, all passing
against the current build.

Figures were produced on **2026-08-18**. The Census inputs (ACS 5-year 2023, TIGER 2023)
are fixed releases and reproduce exactly. OpenStreetMap — the walk network and land use —
is live and edited continuously, so a rebuild shifts these numbers by a point or two.
Pinning it would mean committing 517 MB of walk graphs for data that is fully re-derivable,
so the verifier checks this document against whatever build is on disk rather than a frozen
snapshot.
