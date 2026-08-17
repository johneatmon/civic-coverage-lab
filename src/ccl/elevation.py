"""Node elevations from USGS 3DEP, and slope-aware walking speed.

3DEP's dynamic ImageServer is public and needs no API key, which keeps the pipeline
reproducible for anyone cloning the repo.

Speed model: Tobler's hiking function, renormalised so each profile's speed on flat ground
is its own published flat speed rather than Tobler's 1.4 m/s. Tobler peaks slightly
downhill (-5% grade), which is the right shape for walking.

For wheelchair users a speed penalty alone is the wrong model: above the ADA maximum
running slope the route is not slow, it is unusable. Profiles carrying a `max_grade` treat
steeper edges as impassable, so those areas drop out of the reachable set entirely.
"""

import io
from pathlib import Path

import numpy as np
import rasterio
import requests

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

SERVICE = ("https://elevation.nationalmap.gov/arcgis/rest/services/"
           "3DEPElevation/ImageServer/exportImage")
TARGET_M = 15.0  # DEM sample spacing
MAX_PX = 4000  # ImageServer per-request limit
TOBLER_FLAT = np.exp(-3.5 * 0.05)  # Tobler's value at zero grade, for renormalising


def fetch_dem(city_key: str, bounds: tuple, crs_epsg: int = 32610) -> tuple:
    """Download a DEM covering `bounds` (in the given projected CRS). Returns (array, transform)."""
    cache = DATA / f"dem_{city_key}.tif"
    if not cache.exists():
        minx, miny, maxx, maxy = bounds
        pad = 500.0
        minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
        w = min(int((maxx - minx) / TARGET_M), MAX_PX)
        h = min(int((maxy - miny) / TARGET_M), MAX_PX)
        r = requests.get(SERVICE, params={
            "bbox": f"{minx},{miny},{maxx},{maxy}", "bboxSR": crs_epsg,
            "size": f"{w},{h}", "imageSR": crs_epsg, "format": "tiff",
            "pixelType": "F32", "interpolation": "RSP_BilinearInterpolation", "f": "image",
        }, timeout=600)
        r.raise_for_status()
        if not r.headers.get("content-type", "").startswith("image"):
            raise RuntimeError(f"3DEP returned {r.headers.get('content-type')}: {r.text[:200]}")
        cache.write_bytes(r.content)
    with rasterio.open(cache) as ds:
        return ds.read(1).astype(np.float64), ds.transform


def sample(dem: np.ndarray, transform, xy: np.ndarray) -> np.ndarray:
    """Nearest-pixel elevation for projected coordinates."""
    inv = ~transform
    cols, rows = inv * (xy[:, 0], xy[:, 1])
    rows = np.clip(np.round(rows).astype(int), 0, dem.shape[0] - 1)
    cols = np.clip(np.round(cols).astype(int), 0, dem.shape[1] - 1)
    z = dem[rows, cols]
    return np.where(z < -100, np.nan, z)  # 3DEP nodata


def speed(grade: np.ndarray, flat_mps: float) -> np.ndarray:
    """Tobler's hiking function renormalised to `flat_mps` at zero grade."""
    return flat_mps * np.exp(-3.5 * np.abs(grade + 0.05)) / TOBLER_FLAT


def edge_seconds(length: np.ndarray, grade: np.ndarray, flat_mps: float,
                 max_grade: float | None) -> np.ndarray:
    """Travel time per edge, with impassable edges returned as inf."""
    v = speed(grade, flat_mps)
    t = np.divide(length, v, out=np.full_like(length, np.inf), where=v > 1e-6)
    if max_grade is not None:
        t = np.where(np.abs(grade) > max_grade, np.inf, t)
    return t
