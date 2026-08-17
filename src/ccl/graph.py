"""Shared walk-graph plumbing: a scipy CSR matrix and grid-cell -> node index mapping.

networkx Dijkstra is too slow to run inside a siting loop. scipy's csgraph.dijkstra with
min_only=True computes the whole multi-source nearest-facility field in one C-level pass,
which makes recomputing coverage after each placement cheap enough to run adaptively.
"""

from pathlib import Path

import networkx as nx
import numpy as np
import osmnx as ox
from scipy.spatial import cKDTree
from scipy.sparse import csr_matrix

from ccl.fields import CRS_M, load_walk_graph

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def build_csr(G: nx.MultiDiGraph, nodes: list) -> csr_matrix:
    """CSR adjacency with edge weight = length.

    to_scipy_sparse_array *sums* parallel edges on a multigraph, which is wrong for a
    shortest-path weight, so parallel edges are collapsed to their minimum here.
    """
    idx = {n: i for i, n in enumerate(nodes)}
    best: dict[tuple[int, int], float] = {}
    for u, v, d in G.edges(data=True):
        key = (idx[u], idx[v])
        w = float(d.get("length", 0.0))
        if key not in best or w < best[key]:
            best[key] = w
    rows = np.fromiter((k[0] for k in best), dtype=np.int32, count=len(best))
    cols = np.fromiter((k[1] for k in best), dtype=np.int32, count=len(best))
    vals = np.fromiter(best.values(), dtype=np.float64, count=len(best))
    n = len(nodes)
    return csr_matrix((vals, (rows, cols)), shape=(n, n))


def load() -> dict:
    """Projected graph as CSR, plus the node index and snap distance for every grid cell."""
    cache = DATA / "graph_cache.npz"
    d = np.load(DATA / "fields_libraries.npz")
    xs, ys = d["xs"], d["ys"]

    if cache.exists():
        z = np.load(cache, allow_pickle=False)
        csr = csr_matrix((z["data"], z["indices"], z["indptr"]), shape=tuple(z["shape"]))
        return {"csr": csr, "cell_node": z["cell_node"], "node_xy": z["node_xy"],
                "xs": xs, "ys": ys}

    Gp = ox.project_graph(load_walk_graph(), to_crs=CRS_M)
    nodes = list(Gp.nodes)
    node_xy = np.array([[Gp.nodes[n]["x"], Gp.nodes[n]["y"]] for n in nodes])
    csr = build_csr(Gp, nodes)

    gx, gy = np.meshgrid(xs, ys)
    _, cell_node = cKDTree(node_xy).query(np.column_stack([gx.ravel(), gy.ravel()]))
    cell_node = cell_node.reshape(gx.shape).astype(np.int32)

    np.savez_compressed(cache, data=csr.data, indices=csr.indices, indptr=csr.indptr,
                        shape=np.array(csr.shape), cell_node=cell_node, node_xy=node_xy)
    return {"csr": csr, "cell_node": cell_node, "node_xy": node_xy, "xs": xs, "ys": ys}
