"""Build the two nearest-facility distance fields over Seattle.

Euclidean field: straight-line distance from each grid cell to the nearest facility.
Network field:   walk-network shortest-path distance, via one multi-source Dijkstra
                 seeded at every facility node.

Both are rasterised on the same grid so the persistence comparison is apples-to-apples.
"""

from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CRS_M = "EPSG:32610"  # UTM 10N, metres
GRID_M = 150  # grid cell size in metres
WALK_MPS = 1.4  # walking speed, metres/second


def load_boundary() -> gpd.GeoDataFrame:
    cache = DATA / "seattle_boundary.geojson"
    if cache.exists():
        return gpd.read_file(cache)
    gdf = ox.geocode_to_gdf("Seattle, Washington, USA")
    gdf.to_file(cache, driver="GeoJSON")
    return gdf


def load_walk_graph() -> nx.MultiDiGraph:
    cache = DATA / "seattle_walk.graphml"
    if cache.exists():
        return ox.load_graphml(cache)
    boundary = load_boundary()
    # retain_all=True is essential here: Seattle's walk network is not one connected
    # component. West Seattle attaches only via bridges whose pedestrian ways are not
    # continuously tagged, so dropping to the largest component silently deletes a
    # quarter of the city -- including five library branches.
    G = ox.graph_from_polygon(
        boundary.union_all(), network_type="walk", simplify=True, retain_all=True
    )
    ox.save_graphml(G, cache)
    return G


def build_grid(boundary: gpd.GeoDataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Regular grid over the boundary bbox. Returns (xs, ys, inside_mask[ny, nx])."""
    poly = boundary.to_crs(CRS_M).union_all()
    minx, miny, maxx, maxy = poly.bounds
    xs = np.arange(minx, maxx + GRID_M, GRID_M)
    ys = np.arange(miny, maxy + GRID_M, GRID_M)
    gx, gy = np.meshgrid(xs, ys)
    pts = gpd.GeoSeries(gpd.points_from_xy(gx.ravel(), gy.ravel()), crs=CRS_M)
    inside = pts.within(poly).to_numpy().reshape(gx.shape)
    return xs, ys, inside


def euclidean_field(xs, ys, facilities_m: gpd.GeoDataFrame) -> np.ndarray:
    gx, gy = np.meshgrid(xs, ys)
    fac = np.column_stack([facilities_m.geometry.x, facilities_m.geometry.y])
    tree = cKDTree(fac)
    d, _ = tree.query(np.column_stack([gx.ravel(), gy.ravel()]))
    return d.reshape(gx.shape)


def network_field(xs, ys, facilities_m, G) -> tuple[np.ndarray, np.ndarray]:
    """Network distance field, plus the snap distance from each cell to its node.

    Returns (dist[ny, nx] in metres, snap[ny, nx] in metres). Cells whose nearest
    facility is unreachable get np.inf.
    """
    Gp = ox.project_graph(G, to_crs=CRS_M)
    nodes = list(Gp.nodes)
    node_xy = np.array([[Gp.nodes[n]["x"], Gp.nodes[n]["y"]] for n in nodes])
    node_tree = cKDTree(node_xy)

    # Snap facilities to their nearest network node.
    fac_xy = np.column_stack([facilities_m.geometry.x, facilities_m.geometry.y])
    _, fac_idx = node_tree.query(fac_xy)
    sources = {nodes[i] for i in fac_idx}

    # One multi-source Dijkstra gives nearest-facility distance for every node.
    dist_by_node = nx.multi_source_dijkstra_path_length(Gp, sources, weight="length")

    gx, gy = np.meshgrid(xs, ys)
    cell_xy = np.column_stack([gx.ravel(), gy.ravel()])
    snap, cell_idx = node_tree.query(cell_xy)
    node_dist = np.array([dist_by_node.get(nodes[i], np.inf) for i in cell_idx])

    # Walking from the cell to the network counts too.
    total = node_dist + snap
    return total.reshape(gx.shape), snap.reshape(gx.shape)


def build(resource: str) -> dict:
    boundary = load_boundary()
    facilities = gpd.read_file(DATA / f"{resource}.geojson").to_crs(CRS_M)
    G = load_walk_graph()

    xs, ys, inside = build_grid(boundary)
    euc = euclidean_field(xs, ys, facilities)
    net, snap = network_field(xs, ys, facilities, G)

    return {
        "xs": xs,
        "ys": ys,
        "inside": inside,
        "euclidean": euc,
        "network": net,
        "snap": snap,
        "n_facilities": len(facilities),
        "grid_m": GRID_M,
        "walk_mps": WALK_MPS,
    }


if __name__ == "__main__":
    import sys

    resource = sys.argv[1] if len(sys.argv) > 1 else "libraries"
    out = build(resource)
    np.savez_compressed(DATA / f"fields_{resource}.npz", **{
        k: v for k, v in out.items() if isinstance(v, np.ndarray)
    })
    ins = out["inside"]
    e, n = out["euclidean"][ins], out["network"][ins]
    finite = np.isfinite(n)
    print(f"resource        : {resource} ({out['n_facilities']} facilities)")
    print(f"grid            : {ins.shape} cells, {ins.sum()} inside city, {out['grid_m']}m")
    print(f"unreachable     : {(~finite).sum()} cells")
    print(f"euclidean  mean : {e.mean():7.0f} m   max {e.max():7.0f} m")
    print(f"network    mean : {n[finite].mean():7.0f} m   max {n[finite].max():7.0f} m")
    print(f"detour ratio    : {(n[finite] / np.maximum(e[finite], 1)).mean():.2f} mean")
