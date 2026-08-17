"""Fetch Seattle facility point layers from the Seattle City GIS ArcGIS services."""

from pathlib import Path

import geopandas as gpd
import requests

ARCGIS_ROOT = "https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services"

LAYERS = {
    "fire_stations": "Fire_Stations",
    "libraries": "Seattle_Public_Library",
    "community_centers": "Community_Centers",
}

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def fetch_layer(service: str) -> gpd.GeoDataFrame:
    url = f"{ARCGIS_ROOT}/{service}/FeatureServer/0/query"
    params = {"where": "1=1", "outFields": "*", "outSR": "4326", "f": "geojson"}
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    gdf = gpd.GeoDataFrame.from_features(r.json()["features"], crs="EPSG:4326")
    return gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    for name, service in LAYERS.items():
        gdf = fetch_layer(service)
        out = DATA_DIR / f"{name}.geojson"
        gdf.to_file(out, driver="GeoJSON")
        print(f"{name:20s} {len(gdf):4d} features -> {out.name}")


if __name__ == "__main__":
    main()
