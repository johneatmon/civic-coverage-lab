"""City-parameterised pipeline: facilities, walk network, distance field, demand rasters.

Supersedes the Seattle-only fetch.py / fields.py / demand.py path. Everything is keyed by
city so Seattle and Tacoma can be built and compared with identical machinery.
"""

import io
import os
import zipfile
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
import requests
from dotenv import load_dotenv
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from scipy.sparse import csr_matrix

from ccl.cities import PROFILES, City, get
from ccl.elevation import edge_seconds, fetch_dem, sample
from ccl.graph import build_csr
from ccl.landuse import mask as landuse_mask

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CRS_M = "EPSG:32610"  # default only; each city carries its own UTM zone
GRID_M = 150
SNAP_MAX_M = 250.0
MIN_DENSITY = 100.0
ACS_YEAR = 2023

ARCGIS_ROOT = "https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services"

# Block-group tables. Only B01003 and B01001 survive at this geography.
BG_VARS = {"B01003_001E": "population"}
BG_65 = ["B01001_0%02dE" % i for i in list(range(20, 26)) + list(range(44, 50))]
# Tract-only tables. B08201 (vehicles), B17001 (poverty), B18105 (ambulatory difficulty)
# all return 200 OK with every value null at block-group level.
TRACT_VARS = {
    "B17001_002E": "below_poverty",
    "B08201_001E": "households",
    "B08201_002E": "no_vehicle_hh",
}
TRACT_AMB = ["B18105_0%02dE" % i for i in (4, 7, 10, 13, 16, 20, 23, 26, 29, 32)]


# ------------------------------------------------------------------ facilities


def fetch_facilities(city: City) -> gpd.GeoDataFrame:
    out = DATA / f"{city.key}_facilities.geojson"
    if out.exists():
        return gpd.read_file(out)
    if city.facility_source in ("arcgis", "arcgis_url"):
        url = (city.arcgis_url if city.facility_source == "arcgis_url"
               else f"{ARCGIS_ROOT}/{city.arcgis_service}/FeatureServer/0/query")
        r = requests.get(
            url,
            params={"where": "1=1", "outFields": "*", "outSR": "4326", "f": "geojson"},
            timeout=90,
        )
        r.raise_for_status()
        gdf = gpd.GeoDataFrame.from_features(r.json()["features"], crs="EPSG:4326")
    else:
        f = city.osm_filter
        gdf = ox.features_from_place(city.place, tags=f["tags"]).reset_index()
        if "website_contains" in f:
            web = gdf.get("website", pd.Series(index=gdf.index, dtype=object)).fillna("")
            gdf = gdf[web.str.contains(f["website_contains"], case=False, na=False)]
        gdf = gdf[["name", "geometry"]].copy()
        gdf["geometry"] = gdf.geometry.centroid  # ways -> points
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    gdf.to_file(out, driver="GeoJSON")
    return gdf


# ------------------------------------------------------------------ geography


def boundary(city: City) -> gpd.GeoDataFrame:
    c = DATA / f"{city.key}_boundary.geojson"
    if not c.exists():
        ox.geocode_to_gdf(city.place).to_file(c, driver="GeoJSON")
    return gpd.read_file(c)


def walk_graph(city: City) -> nx.MultiDiGraph:
    c = DATA / f"{city.key}_walk.graphml"
    if not c.exists():
        # retain_all=True is essential: a city's walk network is generally NOT one
        # connected component (Seattle's West Seattle attaches only via bridges whose
        # pedestrian ways are not continuously tagged), and the default silently
        # deletes everything outside the largest component.
        G = ox.graph_from_polygon(boundary(city).union_all(), network_type="walk",
                                  simplify=True, retain_all=True)
        ox.save_graphml(G, c)
    return ox.load_graphml(c)


def grid(city: City):
    poly = boundary(city).to_crs(city.crs).union_all()
    minx, miny, maxx, maxy = poly.bounds
    xs = np.arange(minx, maxx + GRID_M, GRID_M)
    ys = np.arange(miny, maxy + GRID_M, GRID_M)
    gx, gy = np.meshgrid(xs, ys)
    pts = gpd.GeoSeries(gpd.points_from_xy(gx.ravel(), gy.ravel()), crs=city.crs)
    return xs, ys, pts.within(poly).to_numpy().reshape(gx.shape)


# ------------------------------------------------------------------ census


def _acs(city: City, geo: str, codes: list[str]) -> pd.DataFrame:
    load_dotenv(ROOT / ".env")
    inn = f"state:{city.state} county:{city.county}"
    if geo == "block group":
        inn += " tract:*"
    r = requests.get(
        f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5",
        params={"get": "NAME," + ",".join(codes), "for": f"{geo}:*", "in": inn,
                "key": os.environ["CENSUS_DATA_API_KEY"]},
        timeout=180,
    )
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    for c in codes:
        v = pd.to_numeric(df[c], errors="coerce")
        if v.isna().all():
            raise RuntimeError(f"{c} all-null at {geo!r} -- wrong geography for this table")
        df[c] = v.clip(lower=0).fillna(0)
    df["GEOID"] = df["state"] + df["county"] + df["tract"]
    if geo == "block group":
        df["GEOID"] += df["block group"]
    return df


def _shp(url: str, name: str) -> gpd.GeoDataFrame:
    c = DATA / name
    if not c.exists():
        r = requests.get(url, timeout=600)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            z.extractall(c)
    return gpd.read_file(next(c.glob("*.shp")))


def _geoms(city: City, geo: str) -> gpd.GeoDataFrame:
    kind = "bg" if geo == "block group" else "tract"
    g = _shp(f"https://www2.census.gov/geo/tiger/GENZ{ACS_YEAR}/shp/"
             f"cb_{ACS_YEAR}_{city.state}_{kind}_500k.zip", f"cb_{kind}_{city.state}")
    return g[g["COUNTYFP"] == city.county].to_crs(city.crs)


def _water(city: City) -> gpd.GeoDataFrame:
    return _shp(f"https://www2.census.gov/geo/tiger/TIGER{ACS_YEAR}/AREAWATER/"
                f"tl_{ACS_YEAR}_{city.state}{city.county}_areawater.zip",
                f"areawater_{city.state}{city.county}").to_crs(city.crs)


def demand_rasters(city: City, xs, ys, alloc: np.ndarray | None = None,
                   water: np.ndarray | None = None,
                   nonres: np.ndarray | None = None) -> dict:
    """Rasterise ACS counts, allocated dasymetrically onto habitable land.

    Spreading a block group's population evenly over its whole area puts phantom
    residents in its parks, ports and airfields -- which then register as underserved
    demand and attract siting markers. Instead each unit's count is divided among only
    its habitable cells, which conserves the unit total and puts people where they live.
    """
    gx, gy = np.meshgrid(xs, ys)
    cells = gpd.GeoDataFrame(geometry=gpd.points_from_xy(gx.ravel(), gy.ravel()),
                             crs=city.crs)
    out: dict[str, np.ndarray] = {}
    cell_km2 = (GRID_M / 1000.0) ** 2
    alloc_flat = None if alloc is None else alloc.ravel()
    # The habitable *fraction* must be measured on a pure land-use domain. Including the
    # city-boundary or distance-to-network conditions here would put cells in the
    # denominator that can never be in the numerator, deflating the fraction and
    # inflating density for every unit that straddles the boundary.
    land_all = None if water is None else (~water).ravel()
    hab_all = None if land_all is None else (land_all & ~nonres.ravel())

    plans = [
        ("block group", {**BG_VARS}, {"pop_65plus": BG_65}),
        ("tract", {**TRACT_VARS}, {"pop_ambulatory": TRACT_AMB}),
    ]
    for geo, direct, summed in plans:
        codes = list(direct) + [c for v in summed.values() for c in v]
        df = _acs(city, geo, codes)
        for name, cols in summed.items():
            df[name] = df[cols].sum(axis=1)
        for code, name in direct.items():
            df[name] = df[code]
        keep = ["GEOID", *direct.values(), *summed]
        units = _geoms(city, geo).merge(df[keep], on="GEOID", how="left")
        units["land_km2"] = units["ALAND"] / 1e6
        names = list(direct.values()) + list(summed)
        for n in names:
            units[n + "_d"] = np.where(units["land_km2"] > 0,
                                       units[n] / units["land_km2"], 0.0)
        j = gpd.sjoin(cells, units, how="left", predicate="within")
        j = j[~j.index.duplicated(keep="first")].reindex(cells.index)
        uidx = j["index_right"].to_numpy()
        valid = ~np.isnan(uidx)
        ui = np.where(valid, np.nan_to_num(uidx), -1).astype(int)
        nunits = len(units)

        if alloc_flat is None:
            for n in names:
                d = np.nan_to_num(j[n + "_d"].to_numpy(dtype=float)).reshape(gx.shape)
                out[n + "_density"] = d
                out[n] = d * cell_km2
            continue

        # Habitable fraction of each unit, estimated from the grid sample, applied to its
        # true land area. Density stays a per-unit constant, so a block group straddling
        # the city boundary contributes only its in-city share -- normalising by a count
        # of in-grid cells instead would dump its whole population inside the line.
        hab = np.bincount(ui[valid & hab_all], minlength=nunits)
        allc = np.bincount(ui[valid & land_all], minlength=nunits)
        frac = np.divide(hab, allc, out=np.ones(nunits), where=allc > 0)
        frac = np.clip(frac, 0.02, 1.0)  # never divide a unit's population by ~zero area
        hab_km2 = np.maximum(units["land_km2"].to_numpy(dtype=float) * frac, 1e-6)

        for n in names:
            vals = np.nan_to_num(units[n].to_numpy(dtype=float))
            dens = vals / hab_km2
            take = np.zeros(len(ui), dtype=float)
            ok = valid & alloc_flat
            take[ok] = dens[ui[ok]]
            arr = take.reshape(gx.shape)
            out[n + "_density"] = arr
            out[n] = arr * cell_km2

    if alloc_flat is None:
        out["water"] = cells.within(_water(city).union_all()).to_numpy().reshape(gx.shape)
    return out


def _water_mask(city: City, xs, ys) -> np.ndarray:
    gx, gy = np.meshgrid(xs, ys)
    cells = gpd.GeoSeries(gpd.points_from_xy(gx.ravel(), gy.ravel()), crs=city.crs)
    return cells.within(_water(city).union_all()).to_numpy().reshape(gx.shape)


# ------------------------------------------------------------------ assembly


def build(city_key: str) -> dict:
    city = get(city_key)
    xs, ys, inside = grid(city)
    fac = fetch_facilities(city).to_crs(city.crs)
    G = ox.project_graph(walk_graph(city), to_crs=city.crs)

    nodes = list(G.nodes)
    node_xy = np.array([[G.nodes[n]["x"], G.nodes[n]["y"]] for n in nodes])
    tree = cKDTree(node_xy)
    csr = build_csr(G, nodes)

    gx, gy = np.meshgrid(xs, ys)
    snap, cell_node = tree.query(np.column_stack([gx.ravel(), gy.ravel()]))
    snap = snap.reshape(gx.shape)
    cell_node = cell_node.reshape(gx.shape).astype(np.int32)

    _, fac_idx = tree.query(np.column_stack([fac.geometry.x, fac.geometry.y]))
    fac_nodes = np.unique(fac_idx)

    # Flat-distance fields (metres), kept so the slope effect can be isolated.
    # Transposed: a path from a facility in the reversed graph is a path *to* it in the
    # original, which is the direction accessibility is defined in.
    dn = dijkstra(csr.T.tocsr(), indices=fac_nodes, min_only=True)
    network = dn[cell_node] + snap
    euclid = cKDTree(np.column_stack([fac.geometry.x, fac.geometry.y])).query(
        np.column_stack([gx.ravel(), gy.ravel()]))[0].reshape(gx.shape)

    # Slope-aware travel time (seconds), one field per walker profile.
    dem, transform = fetch_dem(city.key, tuple(boundary(city).to_crs(city.crs).total_bounds),
                               crs_epsg=int(city.crs.split(":")[1]))
    elev = sample(dem, transform, node_xy)
    elev = np.where(np.isnan(elev), np.nanmedian(elev), elev)

    coo = csr.tocoo()
    length = coo.data
    rise = elev[coo.col] - elev[coo.row]
    grade = np.divide(rise, length, out=np.zeros_like(length), where=length > 0.5)
    grade = np.clip(grade, -0.6, 0.6)  # guard against DEM noise on very short edges

    time_fields, impassable = {}, {}
    for p in PROFILES:
        secs = edge_seconds(length, grade, p.speed_mps, p.max_grade)
        keep = np.isfinite(secs)
        tm = csr_matrix((secs[keep], (coo.row[keep], coo.col[keep])), shape=csr.shape)
        tn = dijkstra(tm.T.tocsr(), indices=fac_nodes, min_only=True)
        # walking from the cell centre to the network, at the profile's flat speed
        time_fields[f"time_{p.key}"] = tn[cell_node] + snap / p.speed_mps
        impassable[p.key] = float((~keep).sum()) / len(secs)

    # Water and large non-residential land first, so population can be allocated onto
    # habitable cells rather than smeared across parks and port terminals.
    water = demand_rasters(city, xs, ys)["water"] if False else None
    water = _water_mask(city, xs, ys)
    nonres = landuse_mask(city, xs, ys)
    land = inside & (snap <= SNAP_MAX_M) & np.isfinite(network) & ~water
    habitable = land & ~nonres

    dem_r = demand_rasters(city, xs, ys, alloc=habitable, water=water, nonres=nonres)
    dem_r["water"] = water
    dem_r["nonresidential"] = nonres
    inhabited = habitable & (dem_r["population_density"] >= MIN_DENSITY)

    payload = {
        "xs": xs, "ys": ys, "inside": inside, "snap": snap, "cell_node": cell_node,
        "network": network, "euclidean": euclid, "land": land,
        "inhabited": inhabited, "habitable": habitable,
        "fac_nodes": fac_nodes, "node_xy": node_xy,
        "csr_data": csr.data, "csr_indices": csr.indices, "csr_indptr": csr.indptr,
        "csr_shape": np.array(csr.shape), "node_elev": elev, "edge_grade": grade,
        **time_fields,
        **{k: v for k, v in dem_r.items()},
    }
    np.savez_compressed(DATA / f"city_{city.key}.npz", **payload)
    return {"city": city, "n_facilities": len(fac), "impassable": impassable, **payload}


def load(city_key: str) -> dict:
    return dict(np.load(DATA / f"city_{city_key}.npz", allow_pickle=False))


if __name__ == "__main__":
    import sys

    for key in sys.argv[1:] or ["seattle", "tacoma"]:
        r = build(key)
        c, land, inh = r["city"], r["land"], r["inhabited"]
        pop = r["population"][land].sum()
        print(f"\n=== {c.place} ===")
        print(f"  facilities        : {r['n_facilities']}")
        print(f"  analysed land     : {land.sum() * 0.0225:,.0f} km2 ({land.sum():,} cells)")
        print(f"  population (raster): {pop:,.0f}  vs published {c.pop_reference:,} "
              f"({100 * pop / c.pop_reference - 100:+.1f}%)")
        print(f"  65+               : {r['pop_65plus'][land].sum():,.0f}")
        print(f"  ambulatory diff.  : {r['pop_ambulatory'][land].sum():,.0f}")
        print(f"  households        : {r['households'][land].sum():,.0f} "
              f"(no vehicle {r['no_vehicle_hh'][land].sum():,.0f})")
        n = r["network"][inh]
        print(f"  walk dist (inhab.): mean {n[np.isfinite(n)].mean():,.0f} m  "
              f"max {n[np.isfinite(n)].max():,.0f} m")
        print(f"  elevation         : {np.nanmin(r['node_elev']):.0f}-"
              f"{np.nanmax(r['node_elev']):.0f} m; "
              f"|grade|>5% on {100 * (np.abs(r['edge_grade']) > 0.05).mean():.1f}% of edges")
        for p in PROFILES:
            tf = r[f"time_{p.key}"][inh] / 60.0
            ok = np.isfinite(tf)
            print(f"    {p.key:9s} median {np.median(tf[ok]):5.1f} min   "
                  f"unreachable {100 * (~ok).mean():4.1f}% of inhabited cells"
                  f"   (impassable edges {100 * r['impassable'][p.key]:.1f}%)")
