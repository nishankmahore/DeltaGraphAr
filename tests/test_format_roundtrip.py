import pyarrow as pa
from deltagraphar.format.schema import (
    Property, PropertyGroup, VertexInfo, EdgeInfo, GraphInfo
)
from deltagraphar.format.paths import (
    vertex_chunk_path, vid_map_chunk_path,
    adj_list_chunk_path, offset_chunk_path, edge_prop_chunk_path,
    graph_yaml_path, vertex_yaml_path, edge_yaml_path,
)
from deltagraphar.format.writer import write_table, write_yaml
from deltagraphar.format.reader import read_adj_list, read_offsets, scan_delta


def test_vertex_info_yaml_roundtrip():
    pg = PropertyGroup(
        properties=[Property("id", "int64"), Property("name", "string")],
        prefix="person_id",
    )
    vi = VertexInfo(label="person", chunk_size=65_536, property_groups=[pg])
    d = vi.to_dict()
    vi2 = VertexInfo.from_dict(d)
    assert vi2.label == "person"
    assert vi2.chunk_size == 65_536
    assert len(vi2.property_groups) == 1
    assert vi2.property_groups[0].properties[0].name == "id"
    assert vi2.property_groups[0].prefix == "person_id"


def test_edge_info_yaml_roundtrip():
    pg = PropertyGroup([Property("weight", "float64")], prefix="e_weight")
    ei = EdgeInfo(
        src_type="person", edge_type="knows", dst_type="person",
        chunk_size=1_048_576, src_chunk_size=65_536,
        property_groups=[pg],
    )
    d = ei.to_dict()
    ei2 = EdgeInfo.from_dict(d)
    assert ei2.src_type == "person"
    assert ei2.edge_type == "knows"
    assert ei2.dst_type == "person"
    assert ei2.chunk_size == 1_048_576
    assert ei2.src_chunk_size == 65_536
    assert ei2.directed is True
    assert len(d["adj_lists"]) == 2
    assert len(ei2.property_groups) == 1
    assert ei2.property_groups[0].prefix == "e_weight"


def test_graph_info_yaml_roundtrip():
    vi = VertexInfo(label="person", chunk_size=65_536)
    ei = EdgeInfo("person", "knows", "person", 1_048_576, 65_536)
    gi = GraphInfo(name="social", prefix="/data/social", vertex_infos=[vi], edge_infos=[ei])
    d = gi.to_dict()
    assert d["vertices"] == ["person.vertex.yml"]
    assert d["edges"] == ["person_knows_person.edge.yml"]
    assert d["version"] == "gar/v1"


def test_graph_info_from_dict():
    vi = VertexInfo(label="person", chunk_size=65_536)
    ei = EdgeInfo("person", "knows", "person", 1_048_576, 65_536)
    gi = GraphInfo(name="social", prefix="/data/social", vertex_infos=[vi], edge_infos=[ei])
    d = gi.to_dict()
    # from_dict requires pre-loaded sub-objects (manifest only stores filenames)
    gi2 = GraphInfo.from_dict(d, vertex_infos=[vi], edge_infos=[ei])
    assert gi2.name == "social"
    assert gi2.prefix == "/data/social"
    assert len(gi2.vertex_infos) == 1
    assert len(gi2.edge_infos) == 1


def test_paths_are_stable():
    assert vertex_chunk_path("person", "person_id", 3) == "vertex/person/person_id/chunk3"
    assert vid_map_chunk_path("person", 2) == "vertex/person/__vid_map__/chunk2"
    assert adj_list_chunk_path("person", "knows", "person", "ordered_by_source", 1, 0) == \
        "edge/person_knows_person/ordered_by_source/adj_list/part1/chunk0"
    assert offset_chunk_path("person", "knows", "person", 1) == \
        "edge/person_knows_person/ordered_by_source/offset/part1/chunk0"
    assert edge_prop_chunk_path("person", "knows", "person", "unordered_by_source", "e_prop", 0, 2) == \
        "edge/person_knows_person/unordered_by_source/e_prop/part0/chunk2"
    assert graph_yaml_path("social") == "social.graph.yml"
    assert vertex_yaml_path("person") == "person.vertex.yml"
    assert edge_yaml_path("person", "knows", "person") == "person_knows_person.edge.yml"


# ---------------------------------------------------------------------------
# M1 round-trip tests — Parquet writer/reader + CSR neighbor lookup
# ---------------------------------------------------------------------------

class _StubBackend:
    """Minimal in-memory backend for format-layer tests (no versioning needed)."""
    def __init__(self):
        self._files: dict[str, bytes] = {}

    def write_file(self, path: str, data: bytes) -> None:
        self._files[path] = data

    def read_file(self, path: str, ref=None) -> bytes:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]

    def list(self, prefix: str, ref=None) -> list[str]:
        return [p for p in self._files if p.startswith(prefix + "/") or p == prefix]


def test_csr_neighbors_roundtrip():
    b = _StubBackend()

    # Tiny static graph: 4 vertices, edges 0->1, 0->2, 1->3, 2->3 (all in vchunk 0)
    adj = pa.table({
        "src_physical": pa.array([0, 0, 1, 2], type=pa.int64()),
        "dst_physical": pa.array([1, 2, 3, 3], type=pa.int64()),
    })
    write_table(b, adj_list_chunk_path("v", "e", "v", "ordered_by_source", 0, 0), adj)

    # offsets[i] = index of first edge with src_physical >= i
    # vertex 0 -> rows [0,2), vertex 1 -> rows [2,3), vertex 2 -> rows [3,4), vertex 3 -> []
    offsets = pa.table({"offset": pa.array([0, 2, 3, 4, 4], type=pa.int64())})
    write_table(b, offset_chunk_path("v", "e", "v", 0), offsets)

    loaded_adj = read_adj_list(b, "v", "e", "v", "ordered_by_source", 0)
    loaded_off = read_offsets(b, "v", "e", "v", 0)

    def neighbors(v_local):
        return loaded_adj[loaded_off[v_local]:loaded_off[v_local + 1]]["dst_physical"].to_pylist()

    assert sorted(neighbors(0)) == [1, 2]
    assert neighbors(1) == [3]
    assert neighbors(2) == [3]
    assert neighbors(3) == []


def test_empty_adj_list_returns_empty_table():
    b = _StubBackend()
    tbl = read_adj_list(b, "v", "e", "v", "ordered_by_source", 0)
    assert len(tbl) == 0
    assert "src_physical" in tbl.schema.names
    assert "dst_physical" in tbl.schema.names


def test_delta_scan():
    b = _StubBackend()
    delta = pa.table({
        "src_physical": pa.array([0, 0, 1], type=pa.int64()),
        "dst_physical": pa.array([5, 6, 7], type=pa.int64()),
    })
    write_table(b, adj_list_chunk_path("v", "e", "v", "unordered_by_source", 0, 0), delta)

    assert sorted(scan_delta(b, "v", "e", "v", 0, 0)) == [5, 6]
    assert scan_delta(b, "v", "e", "v", 0, 1) == [7]
    assert scan_delta(b, "v", "e", "v", 0, 2) == []


def test_read_adj_list_concatenates_multiple_chunks():
    b = _StubBackend()
    chunk0 = pa.table({"src_physical": pa.array([0], pa.int64()), "dst_physical": pa.array([1], pa.int64())})
    chunk1 = pa.table({"src_physical": pa.array([0], pa.int64()), "dst_physical": pa.array([2], pa.int64())})
    write_table(b, adj_list_chunk_path("v", "e", "v", "ordered_by_source", 0, 0), chunk0)
    write_table(b, adj_list_chunk_path("v", "e", "v", "ordered_by_source", 0, 1), chunk1)

    tbl = read_adj_list(b, "v", "e", "v", "ordered_by_source", 0)
    assert len(tbl) == 2
