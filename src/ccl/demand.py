"""Population / vulnerability demand raster, on the same grid as the distance fields.

Two jobs:
  1. Kill the artifacts the spike surfaced. Bridge decks and open water pass a
     "near the walk network" test but have no residents, so they are masked out here
     using TIGER water polygons and a population-density floor.
  2. Weight the holes. A coverage hole containing 15,000 people is not the same finding
     as an equally large hole containing 300.
"""

import io
import os
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CRS_M = "EPSG:32610"

STATE, COUNTY = "53", "033"  # Washington, King County
ACS_YEAR = 2023

# Total population, population below poverty, households with no vehicle available.
# No-vehicle households matter most here: this is a *walking* accessibility question.
#
# Geography differs by table. B17001 and B08201 are NOT published at block-group level
# in ACS5 -- the API returns 200 with the right row count and nulls in every row -- so
# they are pulled at tract resolution instead. Only B01003 survives at block group.
ACS_VARS = {
    "block group": {"B01003_001E": "population"},
    "tract": {"B17001_002E": "below_poverty", "B08201_002E": "no_vehicle_hh"},
}
ALL_VARS = {n for g in ACS_VARS.values() for n in g.values()}

MIN_DENSITY = 100.0  # people per km2; below this a cell is not treated as inhabited


def fetch_acs(geo: str) -> pd.DataFrame:
    load_dotenv(ROOT / ".env")
    key = os.environ["CENSUS_DATA_API_KEY"]
    varmap = ACS_VARS[geo]
    inn = f"state:{STATE} county:{COUNTY}"
    if geo == "block group":
        inn += " tract:*"
    r = requests.get(
        f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5",
        params={"get": "NAME," + ",".join(varmap), "for": f"{geo}:*", "in": inn, "key": key},
        timeout=120,
    )
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    for code, name in varmap.items():
        v = pd.to_numeric(df[code], errors="coerce")
        if v.isna().all():
            raise RuntimeError(f"{code} is all-null at {geo!r} -- wrong geography for this table")
        df[name] = v.clip(lower=0).fillna(0)
    df["GEOID"] = df["state"] + df["county"] + df["tract"]
    if geo == "block group":
        df["GEOID"] += df["block group"]
    return df[["GEOID", *varmap.values()]]


def _download_shp(url: str, cache_name: str) -> gpd.GeoDataFrame:
    cache = DATA / cache_name
    if not cache.exists():
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            z.extractall(cache)
    shp = next(cache.glob("*.shp"))
    return gpd.read_file(shp)


def fetch_geoms(geo: str) -> gpd.GeoDataFrame:
    kind = "bg" if geo == "block group" else "tract"
    gdf = _download_shp(
        f"https://www2.census.gov/geo/tiger/GENZ{ACS_YEAR}/shp/"
        f"cb_{ACS_YEAR}_{STATE}_{kind}_500k.zip",
        f"cb_{kind}_{STATE}",
    )
    return gdf[gdf["COUNTYFP"] == COUNTY].to_crs(CRS_M)


def fetch_water() -> gpd.GeoDataFrame:
    gdf = _download_shp(
        f"https://www2.census.gov/geo/tiger/TIGER{ACS_YEAR}/AREAWATER/"
        f"tl_{ACS_YEAR}_{STATE}{COUNTY}_areawater.zip",
        f"areawater_{STATE}{COUNTY}",
    )
    return gdf.to_crs(CRS_M)


def build(resource: str = "libraries") -> dict:
    d = np.load(DATA / f"fields_{resource}.npz")
    xs, ys = d["xs"], d["ys"]
    grid_m = float(xs[1] - xs[0])
    cell_km2 = (grid_m / 1000.0) ** 2

    gx, gy = np.meshgrid(xs, ys)
    cells = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(gx.ravel(), gy.ravel()), crs=CRS_M
    )

    out = {}
    for geo, varmap in ACS_VARS.items():
        units = fetch_geoms(geo).merge(fetch_acs(geo), on="GEOID", how="left")
        # ALAND is land area only, so density excludes each unit's own water.
        units["land_km2"] = units["ALAND"] / 1e6
        for col in varmap.values():
            units[f"{col}_density"] = np.where(
                units["land_km2"] > 0, units[col] / units["land_km2"], 0.0
            )
        joined = gpd.sjoin(cells, units, how="left", predicate="within")
        joined = joined[~joined.index.duplicated(keep="first")].reindex(cells.index)
        for col in varmap.values():
            dens = np.nan_to_num(joined[f"{col}_density"].to_numpy(dtype=float))
            out[f"{col}_density"] = dens.reshape(gx.shape)
            out[col] = out[f"{col}_density"] * cell_km2

    water = fetch_water().union_all()
    on_water = cells.within(water).to_numpy().reshape(gx.shape)
    out["water"] = on_water
    out["inhabited"] = (out["population_density"] >= MIN_DENSITY) & ~on_water
    return out


if __name__ == "__main__":
    r = build()
    d = np.load(DATA / "fields_libraries.npz")
    base = d["inside"] & (d["snap"] <= 250) & np.isfinite(d["network"])
    np.savez_compressed(DATA / "demand_libraries.npz", **{
        k: v for k, v in r.items() if isinstance(v, np.ndarray)
    })
    print(f"total population in grid : {r['population'][base].sum():,.0f}")
    print(f"  (Seattle is ~755,000)")
    print(f"cells on water           : {r['water'].sum():,}")
    print(f"analysed cells (was)     : {base.sum():,}")
    print(f"  minus water            : {(base & ~r['water']).sum():,}")
    print(f"  minus uninhabited      : {(base & r['inhabited']).sum():,}")
    print(f"population retained      : "
          f"{r['population'][base & r['inhabited']].sum():,.0f} "
          f"({100 * r['population'][base & r['inhabited']].sum() / r['population'][base].sum():.1f}%)")
