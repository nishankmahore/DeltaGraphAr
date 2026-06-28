import pytest
from deltagraphar.versioning.local_backend import LocalBackend
from deltagraphar.store.graphstore import GraphStore
from deltagraphar.format.schema import (
    GraphInfo, VertexInfo, EdgeInfo, PropertyGroup, Property
)
from deltagraphar.format.reader import read_table


def _gs_with_age(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    vi = VertexInfo(
        label="person", chunk_size=4,
        property_groups=[PropertyGroup([Property("age", "int64")], prefix="person_age")],
    )
    gi = GraphInfo(name="g", prefix="", vertex_infos=[vi])
    gs = GraphStore.create(b, gi, vertex_chunk_size=4)
    gs.add_vertices("person", [{"id": str(i), "age": i * 10} for i in range(4)])
    return gs


def test_existing_chunks_byte_identical(tmp_path):
    gs = _gs_with_age(tmp_path)
    old_data = gs.backend.read_file("vertex/person/person_age/chunk0")

    pg2 = PropertyGroup([Property("score", "float64")], prefix="person_score")
    gs.add_property_group("vertex:person", pg2, {str(i): float(i) for i in range(4)})

    assert gs.backend.read_file("vertex/person/person_age/chunk0") == old_data


def test_new_property_readable(tmp_path):
    gs = _gs_with_age(tmp_path)
    pg2 = PropertyGroup([Property("score", "float64")], prefix="person_score")
    gs.add_property_group("vertex:person", pg2, {"0": 1.0, "1": 2.0, "2": 3.0, "3": 4.0})

    tbl = read_table(gs.backend, "vertex/person/person_score/chunk0")
    assert "score" in tbl.schema.names
    assert tbl["score"].to_pylist() == [1.0, 2.0, 3.0, 4.0]


def test_old_snapshot_has_no_new_property(tmp_path):
    gs = _gs_with_age(tmp_path)
    ref_before = gs.backend.log()[-1].ref

    pg2 = PropertyGroup([Property("score", "float64")], prefix="person_score")
    gs.add_property_group("vertex:person", pg2, {"0": 1.0, "1": 2.0, "2": 3.0, "3": 4.0})

    with pytest.raises(FileNotFoundError):
        gs.backend.read_file("vertex/person/person_score/chunk0", ref=ref_before)


def test_schema_updated_in_memory(tmp_path):
    gs = _gs_with_age(tmp_path)
    assert len(gs.graph_info.vertex_infos[0].property_groups) == 1

    pg2 = PropertyGroup([Property("score", "float64")], prefix="person_score")
    gs.add_property_group("vertex:person", pg2, {"0": 1.0, "1": 2.0, "2": 3.0, "3": 4.0})

    assert len(gs.graph_info.vertex_infos[0].property_groups) == 2
    assert gs.graph_info.vertex_infos[0].property_groups[1].prefix == "person_score"


def test_values_aligned_to_physical_order(tmp_path):
    """Values in chunk must be in physical-id order, not insertion order."""
    b = LocalBackend(str(tmp_path / "repo"))
    vi = VertexInfo(label="v", chunk_size=4)
    gi = GraphInfo(name="g", prefix="", vertex_infos=[vi])
    gs = GraphStore.create(b, gi, vertex_chunk_size=4)
    # Add in non-alphabetical order
    gs.add_vertices("v", [{"id": "z"}, {"id": "a"}, {"id": "m"}])
    # Physical IDs: z=0, a=1, m=2

    pg = PropertyGroup([Property("rank", "int64")], prefix="v_rank")
    gs.add_property_group("vertex:v", pg, {"z": 10, "a": 20, "m": 30})

    tbl = read_table(b, "vertex/v/v_rank/chunk0")
    # chunk0 holds physical 0,1,2 → z,a,m → ranks 10,20,30
    assert tbl["rank"].to_pylist() == [10, 20, 30]
