import pytest
from deltagraphar.store.ids import IDMap
from deltagraphar.versioning.local_backend import LocalBackend
from deltagraphar.store.graphstore import GraphStore
from deltagraphar.format.schema import GraphInfo, VertexInfo, EdgeInfo


def test_idmap_assign_and_resolve(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    idmap = IDMap(b, "person", vertex_chunk_size=4)

    mapping = idmap.assign(["alice", "bob", "carol"])
    assert mapping["alice"] == 0
    assert mapping["bob"] == 1
    assert mapping["carol"] == 2

    resolved = idmap.resolve(["alice", "carol"])
    assert resolved["alice"] == 0
    assert resolved["carol"] == 2


def test_idmap_raises_on_unknown(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    idmap = IDMap(b, "person", vertex_chunk_size=4)
    idmap.assign(["alice"])
    with pytest.raises(KeyError):
        idmap.resolve(["dave"])


def test_idmap_chunks_aligned_to_vsize(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    idmap = IDMap(b, "person", vertex_chunk_size=2)
    idmap.assign(["a", "b", "c", "d"])  # physical 0,1 -> chunk0; 2,3 -> chunk1

    from deltagraphar.format.reader import read_table
    from deltagraphar.format.paths import vid_map_chunk_path
    chunk0 = read_table(b, vid_map_chunk_path("person", 0))
    chunk1 = read_table(b, vid_map_chunk_path("person", 1))
    assert len(chunk0) == 2
    assert len(chunk1) == 2


def test_idmap_to_logical(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    idmap = IDMap(b, "person", vertex_chunk_size=4)
    idmap.assign(["alice", "bob"])
    rev = idmap.to_logical([0, 1])
    assert rev[0] == "alice"
    assert rev[1] == "bob"


def test_idmap_time_travel(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    idmap = IDMap(b, "person", vertex_chunk_size=4)
    idmap.assign(["alice"])
    ref1 = b.commit("v1", {})

    idmap.assign(["bob"])
    b.commit("v2", {})

    # At ref1, only alice exists
    with pytest.raises(KeyError):
        idmap.resolve(["bob"], ref=ref1)
    assert idmap.resolve(["alice"], ref=ref1)["alice"] == 0


def _make_gs(tmp_path, **kwargs):
    b = LocalBackend(str(tmp_path / "repo"))
    vi = VertexInfo(label="v", chunk_size=4)
    ei = EdgeInfo(src_type="v", edge_type="e", dst_type="v", chunk_size=16, src_chunk_size=4)
    gi = GraphInfo(name="test", prefix="", vertex_infos=[vi], edge_infos=[ei])
    return GraphStore.create(b, gi, vertex_chunk_size=4, **kwargs)


def test_add_vertices_and_edges(tmp_path):
    gs = _make_gs(tmp_path)
    gs.add_vertices("v", [{"id": "a"}, {"id": "b"}, {"id": "c"}])
    gs.add_edges(("v", "e", "v"), [
        {"src": "a", "dst": "b"},
        {"src": "a", "dst": "c"},
        {"src": "b", "dst": "c"},
    ])

    nbrs = sorted(gs.out_neighbors("v", "a", ("v", "e", "v")))
    assert nbrs == ["b", "c"]
    assert gs.out_neighbors("v", "b", ("v", "e", "v")) == ["c"]
    assert gs.out_neighbors("v", "c", ("v", "e", "v")) == []


def test_out_neighbors_empty_before_any_edges(tmp_path):
    gs = _make_gs(tmp_path)
    gs.add_vertices("v", [{"id": "x"}, {"id": "y"}])
    assert gs.out_neighbors("v", "x", ("v", "e", "v")) == []


def test_neighbors_union_base_and_delta(tmp_path):
    """After compact, adding more edges shows both CSR base and delta in out_neighbors."""
    gs = _make_gs(tmp_path, compaction_min_rows=0, compaction_threshold_ratio=0.0)
    gs.add_vertices("v", [{"id": "x"}, {"id": "y"}, {"id": "z"}])
    gs.add_edges(("v", "e", "v"), [{"src": "x", "dst": "y"}])
    gs.compact(("v", "e", "v"), vchunks=[0])
    gs.add_edges(("v", "e", "v"), [{"src": "x", "dst": "z"}])

    nbrs = sorted(gs.out_neighbors("v", "x", ("v", "e", "v")))
    assert nbrs == ["y", "z"]
