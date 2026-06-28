#!/usr/bin/env python3
"""Neo4j movie graph example ported to DeltaGraphAr.

Recreates the classic Neo4j :play movies dataset:
  Person {name, born}
  Movie  {title, released, tagline}
  ACTED_IN (Person→Movie) {roles}
  DIRECTED (Person→Movie)
  PRODUCED (Person→Movie)
  WROTE    (Person→Movie)
  REVIEWED (Person→Movie) {rating, summary}

Run:
    python examples/neo4j_movies.py
"""
import tempfile
from deltagraphar.versioning.local_backend import LocalBackend
from deltagraphar.store.graphstore import GraphStore
from deltagraphar.format.schema import (
    GraphInfo, VertexInfo, EdgeInfo, PropertyGroup, Property
)

# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

PEOPLE = [
    {"id": "keanu",       "name": "Keanu Reeves",       "born": 1964},
    {"id": "carrie",      "name": "Carrie-Anne Moss",    "born": 1967},
    {"id": "laurence",    "name": "Laurence Fishburne",  "born": 1961},
    {"id": "hugo",        "name": "Hugo Weaving",        "born": 1960},
    {"id": "lilly",       "name": "Lilly Wachowski",     "born": 1967},
    {"id": "lana",        "name": "Lana Wachowski",      "born": 1965},
    {"id": "joel",        "name": "Joel Silver",         "born": 1952},
    {"id": "tom_h",       "name": "Tom Hanks",           "born": 1956},
    {"id": "gary",        "name": "Gary Sinise",         "born": 1955},
    {"id": "robin",       "name": "Robin Wright",        "born": 1966},
    {"id": "robert_z",    "name": "Robert Zemeckis",     "born": 1951},
    {"id": "tom_t",       "name": "Tom Tykwer",          "born": 1965},
    {"id": "audrey",      "name": "Audrey Tautou",       "born": 1976},
    {"id": "paul",        "name": "Paul Bettany",        "born": 1971},
    {"id": "ron",         "name": "Ron Howard",          "born": 1954},
    {"id": "bill_p",      "name": "Bill Paxton",         "born": 1955},
    {"id": "gene",        "name": "Gene Hackman",        "born": 1930},
    {"id": "j_t_walsh",   "name": "J.T. Walsh",          "born": 1943},
    {"id": "nathan",      "name": "Nathan Lane",         "born": 1956},
]

MOVIES = [
    {"id": "matrix",        "title": "The Matrix",               "released": 1999, "tagline": "Welcome to the Real World"},
    {"id": "matrix2",       "title": "The Matrix Reloaded",      "released": 2003, "tagline": "Free your mind"},
    {"id": "matrix3",       "title": "The Matrix Revolutions",   "released": 2003, "tagline": "Everything that has a beginning has an end"},
    {"id": "forrest_gump",  "title": "Forrest Gump",             "released": 1994, "tagline": "Life is like a box of chocolates"},
    {"id": "castaway",      "title": "Cast Away",                "released": 2000, "tagline": "At the edge of the world, his journey begins"},
    {"id": "davincicode",   "title": "The Da Vinci Code",        "released": 2006, "tagline": "Break The Codes"},
    {"id": "cloud_atlas",   "title": "Cloud Atlas",              "released": 2012, "tagline": "Everything is connected"},
    {"id": "apollo13",      "title": "Apollo 13",                "released": 1995, "tagline": "Houston, we have a problem"},
    {"id": "unforgiven",    "title": "Unforgiven",               "released": 1992, "tagline": "It's a hell of a thing, killing a man"},
]

ACTED_IN = [
    {"src": "keanu",    "dst": "matrix",       "roles": "Neo"},
    {"src": "carrie",   "dst": "matrix",       "roles": "Trinity"},
    {"src": "laurence", "dst": "matrix",       "roles": "Morpheus"},
    {"src": "hugo",     "dst": "matrix",       "roles": "Agent Smith"},
    {"src": "keanu",    "dst": "matrix2",      "roles": "Neo"},
    {"src": "carrie",   "dst": "matrix2",      "roles": "Trinity"},
    {"src": "laurence", "dst": "matrix2",      "roles": "Morpheus"},
    {"src": "hugo",     "dst": "matrix2",      "roles": "Agent Smith"},
    {"src": "keanu",    "dst": "matrix3",      "roles": "Neo"},
    {"src": "carrie",   "dst": "matrix3",      "roles": "Trinity"},
    {"src": "laurence", "dst": "matrix3",      "roles": "Morpheus"},
    {"src": "hugo",     "dst": "matrix3",      "roles": "Agent Smith"},
    {"src": "tom_h",    "dst": "forrest_gump", "roles": "Forrest Gump"},
    {"src": "gary",     "dst": "forrest_gump", "roles": "Lt. Dan Taylor"},
    {"src": "robin",    "dst": "forrest_gump", "roles": "Jenny Curran"},
    {"src": "tom_h",    "dst": "castaway",     "roles": "Chuck Noland"},
    {"src": "paul",     "dst": "davincicode",  "roles": "Silas"},
    {"src": "audrey",   "dst": "davincicode",  "roles": "Sophie Neveu"},
    {"src": "tom_h",    "dst": "davincicode",  "roles": "Robert Langdon"},
    {"src": "tom_h",    "dst": "cloud_atlas",  "roles": "Zachry"},
    {"src": "bill_p",   "dst": "apollo13",     "roles": "Fred Haise"},
    {"src": "gene",     "dst": "unforgiven",   "roles": "Little Bill Daggett"},
    {"src": "gene",     "dst": "unforgiven",   "roles": "Little Bill Daggett"},
    {"src": "nathan",   "dst": "unforgiven",   "roles": "Ned Logan"},
]

DIRECTED = [
    {"src": "lilly",    "dst": "matrix"},
    {"src": "lana",     "dst": "matrix"},
    {"src": "lilly",    "dst": "matrix2"},
    {"src": "lana",     "dst": "matrix2"},
    {"src": "lilly",    "dst": "matrix3"},
    {"src": "lana",     "dst": "matrix3"},
    {"src": "robert_z", "dst": "forrest_gump"},
    {"src": "robert_z", "dst": "castaway"},
    {"src": "ron",      "dst": "davincicode"},
    {"src": "tom_t",    "dst": "cloud_atlas"},
    {"src": "lilly",    "dst": "cloud_atlas"},
    {"src": "lana",     "dst": "cloud_atlas"},
    {"src": "ron",      "dst": "apollo13"},
]

PRODUCED = [
    {"src": "joel",     "dst": "matrix"},
    {"src": "joel",     "dst": "matrix2"},
    {"src": "joel",     "dst": "matrix3"},
]

REVIEWED = [
    {"src": "j_t_walsh",  "dst": "forrest_gump", "rating": 95, "summary": "An amazing journey through decades of American history"},
    {"src": "nathan",     "dst": "cloud_atlas",  "rating": 87, "summary": "Mind-bending, ambitious, occasionally confusing"},
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def build_schema():
    person_vi = VertexInfo(
        label="Person",
        chunk_size=65_536,
        property_groups=[
            PropertyGroup([Property("name", "string"), Property("born", "int32")], prefix="person_props"),
        ],
    )
    movie_vi = VertexInfo(
        label="Movie",
        chunk_size=65_536,
        property_groups=[
            PropertyGroup(
                [Property("title", "string"), Property("released", "int32"), Property("tagline", "string")],
                prefix="movie_props",
            ),
        ],
    )
    acted_in_ei = EdgeInfo(
        "Person", "ACTED_IN", "Movie", chunk_size=1_048_576, src_chunk_size=65_536,
        property_groups=[PropertyGroup([Property("roles", "string")], prefix="acted_in_props")],
    )
    directed_ei  = EdgeInfo("Person", "DIRECTED",  "Movie", chunk_size=1_048_576, src_chunk_size=65_536)
    produced_ei  = EdgeInfo("Person", "PRODUCED",  "Movie", chunk_size=1_048_576, src_chunk_size=65_536)
    reviewed_ei  = EdgeInfo(
        "Person", "REVIEWED", "Movie", chunk_size=1_048_576, src_chunk_size=65_536,
        property_groups=[
            PropertyGroup([Property("rating", "int32"), Property("summary", "string")], prefix="reviewed_props"),
        ],
    )
    return GraphInfo(
        name="movies",
        prefix="",
        vertex_infos=[person_vi, movie_vi],
        edge_infos=[acted_in_ei, directed_ei, produced_ei, reviewed_ei],
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def movies_for_person(gs, name_to_id, movie_id_to_title, person_name, etype):
    pid = name_to_id.get(person_name)
    if pid is None:
        return []
    movie_ids = gs.out_neighbors("Person", pid, etype)
    return [movie_id_to_title.get(mid, mid) for mid in movie_ids]


def people_in_movie(gs, movie_name_to_id, person_id_to_name, movie_title, etype):
    mid = movie_name_to_id.get(movie_title)
    if mid is None:
        return []
    # Reverse lookup: scan all persons for edges to this movie
    results = []
    for pid, pname in person_id_to_name.items():
        nbrs = gs.out_neighbors("Person", pid, etype)
        if mid in nbrs:
            results.append(pname)
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with tempfile.TemporaryDirectory() as repo_dir:
        b = LocalBackend(repo_dir)
        gi = build_schema()
        gs = GraphStore.create(b, gi)

        # --- load vertices ---
        gs.add_vertices("Person", PEOPLE)
        gs.add_vertices("Movie", MOVIES)

        ref_vertices = gs.backend.log()[-1].ref
        print(f"Loaded {len(PEOPLE)} persons, {len(MOVIES)} movies  (ref={ref_vertices[:8]})")

        # --- load edges ---
        gs.add_edges(("Person", "ACTED_IN",  "Movie"), ACTED_IN)
        gs.add_edges(("Person", "DIRECTED",  "Movie"), DIRECTED)
        gs.add_edges(("Person", "PRODUCED",  "Movie"), PRODUCED)
        gs.add_edges(("Person", "REVIEWED",  "Movie"), REVIEWED)

        ref_edges = gs.backend.log()[-1].ref
        print(f"Loaded edges: {len(ACTED_IN)} ACTED_IN, {len(DIRECTED)} DIRECTED, "
              f"{len(PRODUCED)} PRODUCED, {len(REVIEWED)} REVIEWED  (ref={ref_edges[:8]})")

        # --- compact all edge types ---
        for etype in [
            ("Person", "ACTED_IN",  "Movie"),
            ("Person", "DIRECTED",  "Movie"),
            ("Person", "PRODUCED",  "Movie"),
            ("Person", "REVIEWED",  "Movie"),
        ]:
            gs.compact(etype)
        print("Compacted all edge types")

        # --- build helper maps ---
        name_to_id       = {p["name"]: p["id"] for p in PEOPLE}
        movie_id_to_title = {m["id"]: m["title"] for m in MOVIES}
        movie_title_to_id = {m["title"]: m["id"] for m in MOVIES}
        person_id_to_name = {p["id"]: p["name"] for p in PEOPLE}

        # --- queries ---
        print()
        print("─── What movies did Keanu Reeves act in? ────────────────────────────")
        keanu_movies = movies_for_person(
            gs, name_to_id, movie_id_to_title, "Keanu Reeves", ("Person", "ACTED_IN", "Movie")
        )
        for m in sorted(keanu_movies):
            print(f"  {m}")

        print()
        print("─── Who directed The Matrix? ─────────────────────────────────────────")
        directors = people_in_movie(
            gs, movie_title_to_id, person_id_to_name, "The Matrix", ("Person", "DIRECTED", "Movie")
        )
        for d in sorted(directors):
            print(f"  {d}")

        print()
        print("─── Who acted in Forrest Gump? ───────────────────────────────────────")
        cast = people_in_movie(
            gs, movie_title_to_id, person_id_to_name, "Forrest Gump", ("Person", "ACTED_IN", "Movie")
        )
        for c in sorted(cast):
            print(f"  {c}")

        print()
        print("─── 2-hop from Tom Hanks via ACTED_IN ────────────────────────────────")
        # Tom Hanks → movies → co-actors (2-hop in a bipartite graph)
        tom_id = name_to_id["Tom Hanks"]
        tom_movies = gs.out_neighbors("Person", tom_id, ("Person", "ACTED_IN", "Movie"))
        co_actors: set[str] = set()
        for mid in tom_movies:
            for pid in people_in_movie(gs, movie_title_to_id, person_id_to_name,
                                       movie_id_to_title[mid], ("Person", "ACTED_IN", "Movie")):
                if pid != "Tom Hanks":
                    co_actors.add(pid)
        for name in sorted(co_actors):
            print(f"  {name}")

        # --- time travel: no edges visible at vertex-only snapshot ---
        print()
        keanu_at_v_ref = gs.out_neighbors(
            "Person", "keanu", ("Person", "ACTED_IN", "Movie"), ref=ref_vertices
        )
        assert keanu_at_v_ref == [], f"expected no edges at vertex-only ref, got {keanu_at_v_ref}"
        print("Time travel OK: ACTED_IN edges not visible at vertex-only snapshot")

        # --- snapshots ---
        snaps = gs.snapshots()
        print(f"Total commits: {len(snaps)}")
        print(f"Latest ref:    {snaps[-1].ref[:8]}")


if __name__ == "__main__":
    main()
