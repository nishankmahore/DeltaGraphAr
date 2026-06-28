"""Property-based tests: correctness invariants under arbitrary edge sequences."""
from __future__ import annotations

import itertools
import tempfile

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from deltagraphar.versioning.local_backend import LocalBackend
from deltagraphar.store.graphstore import GraphStore
from deltagraphar.format.schema import GraphInfo, VertexInfo, EdgeInfo

# Counter to give each Hypothesis example its own unique directory, since
# Hypothesis reuses the pytest tmp_path fixture across examples within one test.
_example_counter = itertools.count()


def _make_gs(base_tmp, *, compact: bool = False):
    """Create a fresh GraphStore in a unique subdirectory of base_tmp."""
    idx = next(_example_counter)
    repo_path = str(base_tmp / f"repo_{idx}")
    b = LocalBackend(repo_path)
    vi = VertexInfo(label="v", chunk_size=4)
    ei = EdgeInfo("v", "e", "v", chunk_size=16, src_chunk_size=4)
    gi = GraphInfo(name="g", prefix="", vertex_infos=[vi], edge_infos=[ei])
    kwargs = dict(vertex_chunk_size=4)
    if compact:
        kwargs.update(compaction_min_rows=0, compaction_threshold_ratio=0.0)
    return GraphStore.create(b, gi, **kwargs)


# Strategy: edge list as list of (src_idx, dst_idx) pairs into a fixed vertex pool
edge_list = st.lists(
    st.tuples(st.integers(0, 7), st.integers(0, 7)),
    min_size=0,
    max_size=30,
)


@given(edges=edge_list)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_neighbors_match_added_edges(edges, tmp_path):
    """out_neighbors must return exactly the destinations added from each source."""
    gs = _make_gs(tmp_path)
    gs.add_vertices("v", [{"id": str(i)} for i in range(8)])

    if not edges:
        return

    records = [{"src": str(s), "dst": str(d)} for s, d in edges]
    gs.add_edges(("v", "e", "v"), records)

    # Build ground truth from the edge list
    from collections import defaultdict
    expected: dict[str, set[str]] = defaultdict(set)
    for s, d in edges:
        expected[str(s)].add(str(d))

    for v in [str(i) for i in range(8)]:
        got = set(gs.out_neighbors("v", v, ("v", "e", "v")))
        assert got == expected[v], f"vertex {v}: expected {expected[v]}, got {got}"


@given(edges=edge_list)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_neighbors_match_after_compact(edges, tmp_path):
    """out_neighbors must return same results before and after compaction."""
    gs = _make_gs(tmp_path, compact=True)
    gs.add_vertices("v", [{"id": str(i)} for i in range(8)])

    if not edges:
        return

    records = [{"src": str(s), "dst": str(d)} for s, d in edges]
    gs.add_edges(("v", "e", "v"), records)

    before = {
        v: sorted(gs.out_neighbors("v", v, ("v", "e", "v")))
        for v in [str(i) for i in range(8)]
    }

    gs.compact(("v", "e", "v"))

    after = {
        v: sorted(gs.out_neighbors("v", v, ("v", "e", "v")))
        for v in [str(i) for i in range(8)]
    }

    assert before == after, f"neighbors changed after compaction:\nbefore={before}\nafter={after}"


@given(
    batch1=edge_list,
    batch2=edge_list,
)
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_two_batch_insert_accumulates(batch1, batch2, tmp_path):
    """Inserting edges in two batches must accumulate correctly."""
    gs = _make_gs(tmp_path)
    gs.add_vertices("v", [{"id": str(i)} for i in range(8)])

    if batch1:
        gs.add_edges(("v", "e", "v"), [{"src": str(s), "dst": str(d)} for s, d in batch1])
    if batch2:
        gs.add_edges(("v", "e", "v"), [{"src": str(s), "dst": str(d)} for s, d in batch2])

    from collections import defaultdict
    expected: dict[str, set[str]] = defaultdict(set)
    for s, d in batch1 + batch2:
        expected[str(s)].add(str(d))

    for v in [str(i) for i in range(8)]:
        got = set(gs.out_neighbors("v", v, ("v", "e", "v")))
        assert got == expected[v], f"vertex {v}: expected {expected[v]}, got {got}"
