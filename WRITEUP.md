# I brought topology to a city planning problem and a 1974 algorithm beat it

There is a nice paper that uses persistent homology — topological data analysis — to find
holes in civic resource coverage. Instead of drawing a circle around each facility and
calling everything inside it "served", it looks at the structure of coverage across every
scale at once and reports the gaps that persist. I liked it enough to build on it.

So I did, on library access in Seattle, Tacoma and Phoenix. Topology found the holes. Then
I benchmarked it against classical operations research on the decision the holes are
supposed to inform — *where should the next branch go?* — and it lost to random guessing.

## The benchmark

Eight new branches, chosen from the same 833-site candidate grid, scored identically on
residents brought within a 15-minute walk:

| strategy | Seattle | Tacoma | Phoenix |
|---|---:|---:|---:|
| **Greedy MCLP** (Church & ReVelle, 1974) | **+84,673** | **+49,620** | **+85,176** |
| random placement (mean of 5 draws) | +33,679 | +18,080 | +21,472 |
| PH ranked by persistence | +25,037 | +3,363 | +10,060 |
| PH ranked by population | +16,409 | +8,550 | +5,813 |
| worst-served point (no topology) | +5,139 | +1,389 | +5,454 |

Three cities, one verdict. **Topological holes are a diagnostic, not an optimiser.**

## Why it loses

Persistence measures how deep a gap is, and marks its most remote point. The trouble is
that remoteness carries almost no information about how many people a branch would reach.
Across the candidate pool, the correlation between a site's travel time from existing
branches and its marginal coverage gain is **+0.01**.

That single number explains the whole table. Random placement draws from the middle of a
distribution whose median site gains 3,575 residents. Every distance-driven rule — both PH
variants, and the worst-point control — deliberately samples the extreme tail of a
quantity that is uncorrelated with the objective, and the extreme tail of "far from
everything" is reliably the emptiest place in the city. Targeting it is worse than not
aiming at all.

### The counterintuitive part

Weighting the holes by population made things *worse* (+16,409 against +25,037). My first
guess was that it selects small dense pockets with little room to gain. The data says the
opposite: population-weighted PH picks the **largest** pockets — median pocket population
168,663, against 67,639 for the persistence ranking.

The bug is subtler and more interesting. Population ranks the *region*; the placement rule
then still puts the branch at the worst-served *point inside that region*. A larger region
has a more extreme extremum, so the weighting selects a better neighbourhood and then a
worse corner of it. The population signal never survives the trip to the decision. Fixing
that means changing the placement rule, not the ranking — at which point you have
reinvented maximal covering, badly.

## Where topology did earn its keep

Not in siting — in **characterising who is excluded**.

The project's original claim was that each modelling step changes the answer. Here is the
ladder, same city, same branches, each rung measured more carefully:

| Seattle | measure | beyond a 15-min walk |
|---|---|---:|
| 1. Straight-line radius | 1,206 m as the crow flies | 35.8% |
| 2. + street network | 1,206 m along the walk graph | 55.4% (+19.7 pp) |
| 3. + terrain | 15 min at 3 mph, slope-adjusted | 57.5% (+2.1 pp) |
| 4. + mobility profile | 15 min at 0.80 m/s, 5% max grade | 92.5% |

**Straight-line coverage understates Seattle's underserved population by 21.7 points —
156,787 people.** That is the number a service-area map drawn with circles gets wrong.

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
| Ambulatory difficulty | 0.80 m/s | 720 m | **92.5%** |

Seattle meets its 15-minute goal for 43% of adults and 7% of residents with an ambulatory
difficulty. Same sentence in the comprehensive plan, two different cities.

Terrain is what separates those rows. Adding slope moves the adult figure about **2
points** and the ambulatory-difficulty figure **12**. Nearly the entire cost of Seattle's
topography is paid by one group.

### A finding that survives its own fragile number

Under the accessible-route grade — 1:20, or 5%, per the 2010 ADA Standards and PROWAG
R302.4.1 — **12,736 Seattle residents with an ambulatory difficulty have no route to any
library that stays within grade.** That is 46% of them.

That count is fragile. Move the threshold across its defensible range (4%–15%) and it
swings from 18,925 to 966. It should never be quoted alone.

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

## What this is not

[UW's Taskar Center](https://tcat.cs.washington.edu/) has been doing pedestrian
accessibility properly for years — AccessMap for routing, and **Walkshed** for exactly this
kind of planner-facing amenity analysis. Crucially, Walkshed runs on
[OS-CONNECT](https://www.washington.edu/news/2025/03/25/os-connect-accessmap-accessible-sidewalks/),
a statewide sidewalk network with curb ramps and crossings. On network fidelity for
Washington they win outright, and anything built on street centrelines — including this —
is a proxy by comparison.

What is different here: the per-profile decomposition with its own population denominators,
the siting-strategy benchmark, and portability. OS-CONNECT is Washington-only; this
pipeline ran Phoenix from the same code by changing a UTM zone and a county FIPS.

The obvious v2 is to swap the OSM centreline network for OS-CONNECT in Washington, which
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
