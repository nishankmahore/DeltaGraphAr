#!/usr/bin/env python3
"""Quickstart: build a small social graph, add edges, compact, time-travel."""
import tempfile
from deltagraphar.versioning.local_backend import LocalBackend
from deltagraphar.store.graphstore import GraphStore
from deltagraphar.format.schema import GraphInfo, VertexInfo, EdgeInfo, PropertyGroup, Property


def main():
    with tempfile.TemporaryDirectory() as repo_dir:
        # --- setup ---
        b = LocalBackend(repo_dir)
        vi = VertexInfo(
            label="person",
            chunk_size=65_536,
            property_groups=[PropertyGroup([Property("name", "string")], prefix="person_name")],
        )
        ei = EdgeInfo("person", "knows", "person", chunk_size=1_048_576, src_chunk_size=65_536)
        gi = GraphInfo(name="social", prefix="", vertex_infos=[vi], edge_infos=[ei])
        gs = GraphStore.create(b, gi)

        # --- add vertices ---
        people = [{"id": str(i), "name": name} for i, name in enumerate(
            ["Alice", "Bob", "Carol", "Dave", "Eve"]
        )]
        gs.add_vertices("person", people)
        print("Added 5 vertices")

        # --- add edges ---
        gs.add_edges(("person", "knows", "person"), [
            {"src": "0", "dst": "1"},  # Alice → Bob
            {"src": "0", "dst": "2"},  # Alice → Carol
            {"src": "1", "dst": "3"},  # Bob → Dave
        ])
        ref_before_compact = gs.backend.log()[-1].ref
        print("Added 3 edges")

        # --- query (delta scan, no compaction yet) ---
        alice_nbrs = gs.out_neighbors("person", "0", ("person", "knows", "person"))
        print(f"Alice's neighbors (delta): {sorted(alice_nbrs)}")

        # --- compact ---
        gs.compact(("person", "knows", "person"))
        print("Compacted")

        # --- query after compact (CSR) ---
        alice_nbrs_post = gs.out_neighbors("person", "0", ("person", "knows", "person"))
        print(f"Alice's neighbors (CSR):   {sorted(alice_nbrs_post)}")
        assert sorted(alice_nbrs) == sorted(alice_nbrs_post)

        # --- time travel ---
        alice_at_ref = gs.out_neighbors(
            "person", "0", ("person", "knows", "person"), ref=ref_before_compact
        )
        print(f"Alice's neighbors at pre-compact ref: {sorted(alice_at_ref)}")
        assert sorted(alice_at_ref) == sorted(alice_nbrs)

        # --- tag and snapshot ---
        gs.tag("v1")
        snaps = gs.snapshots()
        print(f"Snapshots: {len(snaps)} commits, latest={snaps[-1].ref[:8]}")

        print("Quickstart OK")


if __name__ == "__main__":
    main()
