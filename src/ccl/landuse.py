"""Mask land where nobody lives, so it neither absorbs demand nor attracts a siting marker.

Block-group population density smears residents uniformly across a block group, including
across its parks, ports and airfields. That has two bad effects: phantom residents get
counted as underserved, and — because such places are by construction far from everything
— they win the "worst-served point" anchor, producing recommendations like a branch in the
middle of Point Defiance Park or the Port of Tacoma.

Only *large* non-residential polygons are excluded. A minimum area threshold keeps
neighbourhood pocket parks and ballfields from punching holes through genuinely
residential blocks, while still catching a 300 ha regional park or a working port.
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import osmnx as ox

from ccl.cities import City

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

MIN_AREA_M2 = 20_000.0  # 2 ha; below this a green space sits inside a residential block

# Tags whose large polygons are treated as uninhabited.
EXCLUDE_TAGS = {
    "leisure": ["park", "nature_reserve", "golf_course", "garden", "recreation_ground",
                "sports_centre", "stadium"],
    "landuse": ["forest", "industrial", "port", "cemetery", "military", "quarry",
                "landfill", "brownfield", "greenfield", "farmland", "meadow",
                "recreation_ground", "railway", "reservoir", "basin"],
    "natural": ["wood", "scrub", "wetland", "beach", "sand", "bare_rock"],
    "aeroway": ["aerodrome"],
    "military": True,
}


def fetch(city: City) -> gpd.GeoDataFrame:
    cache = DATA / f"{city.key}_landuse.geojson"
    if cache.exists():
        return gpd.read_file(cache)
    g = ox.features_from_place(city.place, tags=EXCLUDE_TAGS)
    g = g[g.geometry.notna()]
    g = g[g.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    g = g.to_crs(city.crs)
    g = g[g.geometry.area >= MIN_AREA_M2]
    keep = [c for c in ("leisure", "landuse", "natural", "aeroway", "military", "name")
            if c in g.columns]
    g = g[[*keep, "geometry"]].reset_index(drop=True)
    g.to_file(cache, driver="GeoJSON")
    return g


def mask(city: City, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Boolean grid: True where the cell centre falls in large non-residential land."""
    g = fetch(city)
    gx, gy = np.meshgrid(xs, ys)
    cells = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(gx.ravel(), gy.ravel()), crs=city.crs)
    hit = gpd.sjoin(cells, g.set_geometry(g.geometry), how="left", predicate="within")
    hit = hit[~hit.index.duplicated(keep="first")].reindex(cells.index)
    return hit["index_right"].notna().to_numpy().reshape(gx.shape)
