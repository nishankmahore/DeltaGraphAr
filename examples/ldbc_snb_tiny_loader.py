#!/usr/bin/env python3
"""Load a tiny synthetic LDBC SNB-style social graph into DeltaGraphAr.

Data is generated in-memory (no external files required). Structure mirrors
the LDBC Social Network Benchmark schema subset:
  Vertex: Person {id, firstName, lastName}
  Edge:   Person-[KNOWS]->Person
"""
import tempfile
from deltagraphar.versioning.local_backend import LocalBackend
from deltagraphar.store.graphstore import GraphStore
from deltagraphar.format.schema import (
    GraphInfo, VertexInfo, EdgeInfo, PropertyGroup, Property
)

# Tiny synthetic dataset — 10 persons, ~20 knows edges
PERSONS = [
    {"id": "1",  "firstName": "Alice",   "lastName": "Smith"},
    {"id": "2",  "firstName": "Bob",     "lastName": "Jones"},
    {"id": "3",  "firstName": "Carol",   "lastName": "White"},
    {"id": "4",  "firstName": "Dave",    "lastName": "Brown"},
    {"id": "5",  "firstName": "Eve",     "lastName": "Davis"},
    {"id": "6",  "firstName": "Frank",   "lastName": "Wilson"},
    {"id": "7",  "firstName": "Grace",   "lastName": "Taylor"},
    {"id": "8",  "firstName": "Heidi",   "lastName": "Anderson"},
    {"id": "9",  "firstName": "Ivan",    "lastName": "Thomas"},
    {"id": "10", "firstName": "Judy",    "lastName": "Jackson"},
]

KNOWS = [
    {"src": "1", "dst": "2"}, {"src": "1", "dst": "3"}, {"src": "1", "dst": "4"},
    {"src": "2", "dst": "3"}, {"src": "2", "dst": "5"},
    {"src": "3", "dst": "6"}, {"src": "3", "dst": "7"},
    {"src": "4", "dst": "8"}, {"src": "4", "dst": "9"},
    {"src": "5", "dst": "6"}, {"src": "5", "dst": "10"},
    {"src": "6", "dst": "7"},
    {"src": "7", "dst": "8"}, {"src": "7", "dst": "9"},
    {"src": "8", "dst": "10"},
    {"src": "9", "dst": "10"},
    {"src": "10", "dst": "1"},
    {"src": "2", "dst": "10"}, {"src": "3", "dst": "9"}, {"src": "4", "dst": "6"},
]


def build_graph(repo_dir: str) -> GraphStore:
    b = LocalBackend(repo_dir)
    vi = VertexInfo(
        label="Person",
        chunk_size=65_536,
        property_groups=[
            PropertyGroup(
                [Property("firstName", "string"), Property("lastName", "string")],
                prefix="person_name",
            )
        ],
    )
    ei = EdgeInfo("Person", "KNOWS", "Person", chunk_size=1_048_576, src_chunk_size=65_536)
    gi = GraphInfo(name="ldbc_snb_tiny", prefix="", vertex_infos=[vi], edge_infos=[ei])
    return GraphStore.create(b, gi)


def main():
    with tempfile.TemporaryDirectory() as repo_dir:
        gs = build_graph(repo_dir)

        gs.add_vertices("Person", PERSONS)
        ref_after_vertices = gs.backend.log()[-1].ref
        print(f"Loaded {len(PERSONS)} persons. ref={ref_after_vertices[:8]}")

        gs.add_edges(("Person", "KNOWS", "Person"), KNOWS)
        ref_after_edges = gs.backend.log()[-1].ref
        print(f"Loaded {len(KNOWS)} knows edges.  ref={ref_after_edges[:8]}")

        gs.compact(("Person", "KNOWS", "Person"))
        print("Compacted KNOWS adjacency.")

        # Sample query: 1-hop neighbors of person "1" (Alice)
        alice_nbrs = sorted(
            gs.out_neighbors("Person", "1", ("Person", "KNOWS", "Person"))
        )
        print(f"Alice (id=1) knows: {alice_nbrs}")

        # 2-hop from Alice
        two_hop = gs.k_hop("Person", "1", ("Person", "KNOWS", "Person"), k=2)
        print(f"2-hop neighborhood of Alice: {sorted(two_hop)}")

        # Time travel: snapshot before edges were added
        nbrs_at_vertex_ref = gs.out_neighbors(
            "Person", "1", ("Person", "KNOWS", "Person"), ref=ref_after_vertices
        )
        assert nbrs_at_vertex_ref == [], f"expected no edges at vertex-only ref, got {nbrs_at_vertex_ref}"
        print("Time travel OK: no edges visible at vertex-only snapshot.")

        snaps = gs.snapshots()
        print(f"Total commits: {len(snaps)}")
        print("LDBC SNB tiny loader OK")


if __name__ == "__main__":
    main()
