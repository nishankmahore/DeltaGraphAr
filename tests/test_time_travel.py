import pytest
from deltagraphar.versioning.local_backend import LocalBackend
from deltagraphar.store.graphstore import GraphStore
from deltagraphar.format.schema import GraphInfo, VertexInfo, EdgeInfo


def _gs(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    vi = VertexInfo(label="v", chunk_size=4)
    ei = EdgeInfo("v", "e", "v", chunk_size=16, src_chunk_size=4)
    gi = GraphInfo(name="g", prefix="", vertex_infos=[vi], edge_infos=[ei])
    return GraphStore.create(b, gi, vertex_chunk_size=4, compaction_min_rows=0, compaction_threshold_ratio=0.0)


def test_out_neighbors_at_historical_ref(tmp_path):
    """Neighbors from before an edge was added must not appear at earlier ref."""
    gs = _gs(tmp_path)
    gs.add_vertices("v", [{"id": "a"}, {"id": "b"}, {"id": "c"}])
    ref_v = gs.backend.log()[-1].ref

    gs.add_edges(("v", "e", "v"), [{"src": "a", "dst": "b"}])
    ref_e1 = gs.backend.log()[-1].ref

    # At ref_v (before any edges) — a has no neighbors
    assert gs.out_neighbors("v", "a", ("v", "e", "v"), ref=ref_v) == []

    # At ref_e1 — a → b
    assert gs.out_neighbors("v", "a", ("v", "e", "v"), ref=ref_e1) == ["b"]


def test_two_edge_epochs(tmp_path):
    """Adding edges in two separate commits; old ref must not see later edges."""
    gs = _gs(tmp_path)
    gs.add_vertices("v", [{"id": str(i)} for i in range(4)])

    gs.add_edges(("v", "e", "v"), [{"src": "0", "dst": "1"}])
    ref1 = gs.backend.log()[-1].ref

    gs.add_edges(("v", "e", "v"), [{"src": "0", "dst": "2"}])
    ref2 = gs.backend.log()[-1].ref

    assert sorted(gs.out_neighbors("v", "0", ("v", "e", "v"), ref=ref1)) == ["1"]
    assert sorted(gs.out_neighbors("v", "0", ("v", "e", "v"), ref=ref2)) == ["1", "2"]


def test_compact_then_time_travel(tmp_path):
    """After compaction, reading a pre-compact ref must still return the delta-era data."""
    gs = _gs(tmp_path)
    gs.add_vertices("v", [{"id": str(i)} for i in range(4)])
    gs.add_edges(("v", "e", "v"), [{"src": "0", "dst": "1"}, {"src": "0", "dst": "2"}])
    ref_pre_compact = gs.backend.log()[-1].ref

    gs.compact(("v", "e", "v"), vchunks=[0])
    ref_post_compact = gs.backend.log()[-1].ref

    # Both refs return same neighbors — base CSR vs delta scan
    pre = sorted(gs.out_neighbors("v", "0", ("v", "e", "v"), ref=ref_pre_compact))
    post = sorted(gs.out_neighbors("v", "0", ("v", "e", "v"), ref=ref_post_compact))
    assert pre == post == ["1", "2"]


def test_snapshots_list_chronological(tmp_path):
    """snapshots() returns commits in oldest-first order."""
    gs = _gs(tmp_path)
    gs.add_vertices("v", [{"id": "a"}])
    gs.add_vertices("v", [{"id": "b"}])
    snaps = gs.snapshots()
    assert len(snaps) >= 2
    for i in range(len(snaps) - 1):
        assert snaps[i].timestamp <= snaps[i + 1].timestamp


def test_tag_pins_snapshot(tmp_path):
    """A tagged ref must return the graph state at tag time, not current state."""
    gs = _gs(tmp_path)
    gs.add_vertices("v", [{"id": "x"}, {"id": "y"}])
    gs.add_edges(("v", "e", "v"), [{"src": "x", "dst": "y"}])
    ref = gs.backend.log()[-1].ref
    gs.tag("v1", ref)

    # Add more edges after tagging
    gs.add_edges(("v", "e", "v"), [{"src": "y", "dst": "x"}])

    # Tag v1 still sees only the original edge
    nbrs_at_tag = gs.out_neighbors("v", "x", ("v", "e", "v"), ref="v1")
    assert nbrs_at_tag == ["y"]
    # y has no back-edge at the tag
    assert gs.out_neighbors("v", "y", ("v", "e", "v"), ref="v1") == []


def test_resolve_time_finds_correct_snapshot(tmp_path):
    """resolve_time returns the ref whose commit is at or just before the query timestamp."""
    import time
    b = LocalBackend(str(tmp_path / "repo"))
    vi = VertexInfo(label="v", chunk_size=4)
    ei = EdgeInfo("v", "e", "v", chunk_size=16, src_chunk_size=4)
    gi = GraphInfo(name="g", prefix="", vertex_infos=[vi], edge_infos=[ei])
    gs = GraphStore.create(b, gi, vertex_chunk_size=4)

    gs.add_vertices("v", [{"id": "a"}, {"id": "b"}])
    gs.add_edges(("v", "e", "v"), [{"src": "a", "dst": "b"}])
    t_mid = time.time()

    time.sleep(0.1)
    gs.add_edges(("v", "e", "v"), [{"src": "b", "dst": "a"}])

    ref = b.resolve_time(t_mid)
    # At t_mid, only a→b edge exists; b→a was added 0.1s later
    nbrs_a = sorted(gs.out_neighbors("v", "a", ("v", "e", "v"), ref=ref))
    nbrs_b = sorted(gs.out_neighbors("v", "b", ("v", "e", "v"), ref=ref))
    assert nbrs_a == ["b"]
    assert nbrs_b == []
