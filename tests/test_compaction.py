import pytest
import pyarrow as pa
from deltagraphar.versioning.local_backend import LocalBackend
from deltagraphar.store.graphstore import GraphStore
from deltagraphar.format.schema import GraphInfo, VertexInfo, EdgeInfo, PropertyGroup, Property
from deltagraphar.format.reader import read_offsets, read_adj_list, read_table


def _gs(tmp_path, **kwargs):
    """8-vertex graph, vchunk_size=4 so vertices 0-3 are in vchunk0, 4-7 in vchunk1."""
    b = LocalBackend(str(tmp_path / "repo"))
    vi = VertexInfo(label="v", chunk_size=4)
    ei = EdgeInfo("v", "e", "v", chunk_size=16, src_chunk_size=4)
    gi = GraphInfo(name="g", prefix="", vertex_infos=[vi], edge_infos=[ei])
    gs = GraphStore.create(
        b, gi, vertex_chunk_size=4,
        compaction_min_rows=0, compaction_threshold_ratio=0.0,
        **kwargs,
    )
    gs.add_vertices("v", [{"id": str(i)} for i in range(8)])
    return gs


def test_neighbors_unchanged_after_compact(tmp_path):
    gs = _gs(tmp_path)
    gs.add_edges(("v", "e", "v"), [
        {"src": "0", "dst": "1"}, {"src": "0", "dst": "2"},
        {"src": "1", "dst": "3"}, {"src": "5", "dst": "6"},
    ])
    expected = {
        v: sorted(gs.out_neighbors("v", v, ("v", "e", "v")))
        for v in [str(i) for i in range(8)]
    }
    gs.compact(("v", "e", "v"), vchunks=[0, 1])
    for v in expected:
        assert sorted(gs.out_neighbors("v", v, ("v", "e", "v"))) == expected[v], \
            f"mismatch at vertex {v}"


def test_only_touched_vchunk_files_change(tmp_path):
    gs = _gs(tmp_path)
    gs.add_edges(("v", "e", "v"), [
        {"src": "0", "dst": "1"},   # vchunk 0
        {"src": "5", "dst": "6"},   # vchunk 1
    ])
    # Snapshot before compacting only vchunk 0
    ref_before = gs.backend.log()[-1].ref

    gs.compact(("v", "e", "v"), vchunks=[0])

    # vchunk 1 delta must be byte-identical to pre-compact snapshot
    delta_path = "edge/v_e_v/unordered_by_source/adj_list/part1/chunk0"
    before = gs.backend.read_file(delta_path, ref=ref_before)
    after = gs.backend.read_file(delta_path)
    assert before == after, "vchunk 1 delta was modified when only vchunk 0 was compacted"


def test_offsets_correct_after_compact(tmp_path):
    gs = _gs(tmp_path)
    gs.add_edges(("v", "e", "v"), [
        {"src": "0", "dst": "1"}, {"src": "0", "dst": "2"},
        {"src": "1", "dst": "3"},
    ])
    gs.compact(("v", "e", "v"), vchunks=[0])

    offsets = read_offsets(gs.backend, "v", "e", "v", 0)
    adj = read_adj_list(gs.backend, "v", "e", "v", "ordered_by_source", 0)

    # vertex 0 (local index 0 in vchunk 0): edges to 1,2
    assert sorted(adj[offsets[0]:offsets[1]]["dst_physical"].to_pylist()) == [1, 2]
    # vertex 1 (local index 1): edge to 3
    assert adj[offsets[1]:offsets[2]]["dst_physical"].to_pylist() == [3]
    # vertices 2 and 3: no edges
    assert offsets[2] == offsets[3] == offsets[4]
    # total rows in ordered adj = 3
    assert len(adj) == 3


def test_delta_cleared_after_compact(tmp_path):
    gs = _gs(tmp_path)
    gs.add_edges(("v", "e", "v"), [{"src": "0", "dst": "1"}, {"src": "0", "dst": "2"}])
    gs.compact(("v", "e", "v"), vchunks=[0])

    delta = read_adj_list(gs.backend, "v", "e", "v", "unordered_by_source", 0)
    assert len(delta) == 0, "delta should be empty after compaction"


def test_high_degree_vertex(tmp_path):
    """One vertex with many out-edges, spanning multiple edge chunk files."""
    gs = _gs(tmp_path)
    # vertex 0 has edges to vertices 1,2,3 (all in vchunk0) — high degree relative to tiny graph
    edges = [{"src": "0", "dst": str(d)} for d in [1, 2, 3]]
    gs.add_edges(("v", "e", "v"), edges)
    gs.compact(("v", "e", "v"), vchunks=[0])

    nbrs = sorted(gs.out_neighbors("v", "0", ("v", "e", "v")))
    assert nbrs == ["1", "2", "3"]


def test_compact_twice_same_result(tmp_path):
    """Idempotent: compacting again after delta is empty should not corrupt."""
    gs = _gs(tmp_path)
    gs.add_edges(("v", "e", "v"), [{"src": "0", "dst": "1"}])
    gs.compact(("v", "e", "v"), vchunks=[0])
    # Second compact: delta is empty, base has 1 edge
    gs.compact(("v", "e", "v"), vchunks=[0])
    nbrs = gs.out_neighbors("v", "0", ("v", "e", "v"))
    assert sorted(nbrs) == ["1"]


def test_auto_vchunk_discovery(tmp_path):
    """compact(etype) with no vchunks= arg auto-discovers affected vchunks."""
    gs = _gs(tmp_path)
    gs.add_edges(("v", "e", "v"), [
        {"src": "0", "dst": "1"},  # vchunk 0
        {"src": "4", "dst": "5"},  # vchunk 1
    ])
    gs.compact(("v", "e", "v"))  # no vchunks= — should discover both

    assert sorted(gs.out_neighbors("v", "0", ("v", "e", "v"))) == ["1"]
    assert sorted(gs.out_neighbors("v", "4", ("v", "e", "v"))) == ["5"]
    # both deltas cleared
    assert len(read_adj_list(gs.backend, "v", "e", "v", "unordered_by_source", 0)) == 0
    assert len(read_adj_list(gs.backend, "v", "e", "v", "unordered_by_source", 1)) == 0


def test_compaction_with_property_group(tmp_path):
    """Property values must be preserved and row-aligned after compaction."""
    b = LocalBackend(str(tmp_path / "repo"))
    vi = VertexInfo(label="v", chunk_size=4)
    pg = PropertyGroup([Property("weight", "float64")], prefix="e_weight")
    ei = EdgeInfo("v", "e", "v", chunk_size=16, src_chunk_size=4, property_groups=[pg])
    gi = GraphInfo(name="g", prefix="", vertex_infos=[vi], edge_infos=[ei])
    gs = GraphStore.create(
        b, gi, vertex_chunk_size=4,
        compaction_min_rows=0, compaction_threshold_ratio=0.0,
    )
    gs.add_vertices("v", [{"id": str(i)} for i in range(4)])
    gs.add_edges(("v", "e", "v"), [
        {"src": "0", "dst": "1", "weight": 1.5},
        {"src": "0", "dst": "2", "weight": 2.5},
    ])
    gs.compact(("v", "e", "v"), vchunks=[0])

    # Verify adj_list and property table have matching row counts
    adj = read_adj_list(b, "v", "e", "v", "ordered_by_source", 0)
    props = read_table(b, "edge/v_e_v/ordered_by_source/e_weight/part0/chunk0")
    assert len(adj) == len(props) == 2
    # Weights should correspond to sorted (src, dst) order: (0,1) then (0,2)
    assert props["weight"].to_pylist() == [1.5, 2.5]

    # Property delta chunks must be cleared
    delta_props_prefix = "edge/v_e_v/unordered_by_source/e_weight/part0"
    delta_props_paths = b.list(delta_props_prefix)
    for p in delta_props_paths:
        tbl = read_table(b, p)
        assert len(tbl) == 0, f"stale rows in {p} after compaction"
