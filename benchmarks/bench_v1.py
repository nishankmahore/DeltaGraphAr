#!/usr/bin/env python3
"""DeltaGraphAr v0.1.0 performance benchmark.

Measures throughput (rows/sec) for the four core operations:
  - add_vertices   : assign logical IDs and write property chunks
  - add_edges      : append to unordered delta
  - compact        : merge delta into ordered CSR
  - out_neighbors  : CSR slice + delta scan

Run with:
    python benchmarks/bench_v1.py [--rows N]
"""
from __future__ import annotations

import argparse
import tempfile
import time

from deltagraphar.versioning.local_backend import LocalBackend
from deltagraphar.store.graphstore import GraphStore
from deltagraphar.format.schema import GraphInfo, VertexInfo, EdgeInfo


def _gs(repo_dir: str, vertex_chunk_size: int = 65_536) -> GraphStore:
    b = LocalBackend(repo_dir)
    vi = VertexInfo(label="v", chunk_size=vertex_chunk_size)
    ei = EdgeInfo("v", "e", "v", chunk_size=1_048_576, src_chunk_size=vertex_chunk_size)
    gi = GraphInfo(name="bench", prefix="", vertex_infos=[vi], edge_infos=[ei])
    return GraphStore.create(
        b, gi,
        vertex_chunk_size=vertex_chunk_size,
        compaction_min_rows=0,
        compaction_threshold_ratio=0.0,
    )


def bench_add_vertices(gs: GraphStore, n: int) -> float:
    records = [{"id": str(i)} for i in range(n)]
    t0 = time.perf_counter()
    gs.add_vertices("v", records)
    return time.perf_counter() - t0


def bench_add_edges(gs: GraphStore, n: int) -> float:
    # Fan-out from vertex 0 to 1..n (or up to available vertices)
    # Count actual vertices by checking IDMap
    idmap = gs._idmap("v")
    fwd, _ = idmap._load_all()
    n_vertices = len(fwd)
    max_dst = min(n + 1, n_vertices - 1)  # vertices are 0..n_vertices-1, so dst can be 1..n_vertices-1
    records = [{"src": "0", "dst": str(i)} for i in range(1, max_dst + 1)]
    t0 = time.perf_counter()
    gs.add_edges(("v", "e", "v"), records)
    return time.perf_counter() - t0


def bench_compact(gs: GraphStore) -> tuple[float, int]:
    t0 = time.perf_counter()
    gs.compact(("v", "e", "v"))
    elapsed = time.perf_counter() - t0
    # Count how many delta rows were merged
    from deltagraphar.format.reader import count_rows
    merged = count_rows(gs.backend, "v", "e", "v", "ordered_by_source", 0)
    return elapsed, merged


def bench_out_neighbors(gs: GraphStore, n_queries: int) -> float:
    t0 = time.perf_counter()
    for _ in range(n_queries):
        gs.out_neighbors("v", "0", ("v", "e", "v"))
    return time.perf_counter() - t0


def fmt(label: str, elapsed: float, count: int):
    rate = count / elapsed if elapsed > 0 else float("inf")
    print(f"  {label:<22}  {elapsed*1000:8.1f} ms   {rate:>12,.0f} rows/sec   ({count:,} rows)")


def main():
    parser = argparse.ArgumentParser(description="DeltaGraphAr v0.1 benchmarks")
    parser.add_argument("--rows", type=int, default=10_000,
                        help="Number of vertices/edges per operation (default: 10000)")
    parser.add_argument("--queries", type=int, default=1_000,
                        help="Number of out_neighbors queries (default: 1000)")
    args = parser.parse_args()

    n = args.rows
    q = args.queries

    print(f"\nDeltaGraphAr v0.1 benchmark  (rows={n:,}, queries={q:,})")
    print("=" * 72)

    with tempfile.TemporaryDirectory() as repo_dir:
        gs = _gs(repo_dir)

        elapsed_v = bench_add_vertices(gs, n)
        fmt("add_vertices", elapsed_v, n)

        # Add edges from vertex 0 to a subset of other vertices
        n_edges = min(n, n - 2)  # max edges is n-2 (can't go back to 0, src is 0)
        elapsed_e = bench_add_edges(gs, n_edges)
        fmt("add_edges", elapsed_e, n_edges)

        elapsed_c, merged = bench_compact(gs)
        fmt("compact", elapsed_c, merged)

        elapsed_q = bench_out_neighbors(gs, q)
        fmt("out_neighbors", elapsed_q, q)

    print("=" * 72)
    print("Done.\n")


if __name__ == "__main__":
    main()
