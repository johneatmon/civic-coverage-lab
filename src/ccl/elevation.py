"""Node elevations from USGS 3DEP, and slope-aware walking speed.

3DEP's dynamic ImageServer is public and needs no API key, which keeps the pipeline
reproducible for anyone cloning the repo.

Speed model: Tobler's hiking function, renormalised so each profile's speed on flat ground
is its own published flat speed rather than Tobler's 1.4 m/s. Tobler peaks slightly
downhill (-5% grade), which is the right shape for walking.

For wheelchair users a speed penalty alone is the wrong model: past the grade an accessible
route is designed to (1:20 / 5%), a route is not merely slow. Profiles carrying a
`max_grade` treat steeper edges as impassable, so those areas drop out of the reachable
set entirely.
"""

import io
import time
from pathlib import Path

import numpy as np
import rasterio
import requests
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

SERVICE = ("https://elevation.nationalmap.gov/arcgis/rest/services/"
           "3DEPElevation/ImageServer/exportImage")
TARGET_M = 15.0  # DEM sample spacing
MAX_PX = 4000  # ImageServer per-request limit
TILE_PX = 1800  # per-tile request size; the service 500s well below its nominal cap
TOBLER_FLAT = np.exp(-3.5 * 0.05)  # Tobler's value at zero grade, for renormalising


def _tile(minx, miny, maxx, maxy, w, h, crs_epsg, attempts=3):
    for i in range(attempts):
        r = requests.get(SERVICE, params={
            "bbox": f"{minx},{miny},{maxx},{maxy}", "bboxSR": crs_epsg,
            "size": f"{w},{h}", "imageSR": crs_epsg, "format": "tiff",
            "pixelType": "F32", "interpolation": "RSP_BilinearInterpolation", "f": "image",
        }, timeout=600)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            with rasterio.open(io.BytesIO(r.content)) as ds:
                return ds.read(1).astype(np.float64)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"3DEP tile failed after {attempts} attempts: HTTP {r.status_code}")


def fetch_dem(city_key: str, bounds: tuple, crs_epsg: int = 32610) -> tuple:
    """DEM covering `bounds` (projected CRS), always at TARGET_M resolution.

    Requests are tiled. A single exportImage call for a large city exceeds the service's
    pixel limit and 500s; clamping the size instead would silently coarsen the DEM for big
    cities only, which would understate their steepness relative to small ones -- exactly
    the cross-city comparison this is used for.
    """
    cache = DATA / f"dem_{city_key}.tif"
    if not cache.exists():
        pad = 500.0
        minx, miny = bounds[0] - pad, bounds[1] - pad
        maxx, maxy = bounds[2] + pad, bounds[3] + pad
        W = int(np.ceil((maxx - minx) / TARGET_M))
        H = int(np.ceil((maxy - miny) / TARGET_M))
        out = np.full((H, W), np.nan, dtype=np.float64)
        for r0 in range(0, H, TILE_PX):
            for c0 in range(0, W, TILE_PX):
                h = min(TILE_PX, H - r0)
                w = min(TILE_PX, W - c0)
                # rows count down from maxy: row 0 is the top of the image
                tx0 = minx + c0 * TARGET_M
                ty1 = maxy - r0 * TARGET_M
                out[r0:r0 + h, c0:c0 + w] = _tile(
                    tx0, ty1 - h * TARGET_M, tx0 + w * TARGET_M, ty1, w, h, crs_epsg)
        transform = from_origin(minx, maxy, TARGET_M, TARGET_M)
        with rasterio.open(cache, "w", driver="GTiff", height=H, width=W, count=1,
                           dtype="float32", crs=f"EPSG:{crs_epsg}",
                           transform=transform, compress="deflate") as ds:
            ds.write(out.astype("float32"), 1)
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
