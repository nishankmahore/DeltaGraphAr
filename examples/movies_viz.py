#!/usr/bin/env python3
"""Build the Neo4j movie graph and render it with matplotlib/networkx.

Run:
    python examples/neo4j_movies_viz.py
"""
import tempfile
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from deltagraphar.versioning.local_backend import LocalBackend
from deltagraphar.store.graphstore import GraphStore
from deltagraphar.format.schema import (
    GraphInfo, VertexInfo, EdgeInfo, PropertyGroup, Property
)

# --- same dataset as neo4j_movies.py ---
PEOPLE = [
    {"id": "keanu",    "name": "Keanu Reeves"},
    {"id": "carrie",   "name": "Carrie-Anne Moss"},
    {"id": "laurence", "name": "Laurence Fishburne"},
    {"id": "hugo",     "name": "Hugo Weaving"},
    {"id": "lilly",    "name": "Lilly Wachowski"},
    {"id": "lana",     "name": "Lana Wachowski"},
    {"id": "joel",     "name": "Joel Silver"},
    {"id": "tom_h",    "name": "Tom Hanks"},
    {"id": "gary",     "name": "Gary Sinise"},
    {"id": "robin",    "name": "Robin Wright"},
    {"id": "robert_z", "name": "Robert Zemeckis"},
    {"id": "audrey",   "name": "Audrey Tautou"},
    {"id": "paul",     "name": "Paul Bettany"},
    {"id": "ron",      "name": "Ron Howard"},
    {"id": "bill_p",   "name": "Bill Paxton"},
]

MOVIES = [
    {"id": "matrix",       "title": "The Matrix",          "released": 1999},
    {"id": "matrix2",      "title": "The Matrix Reloaded", "released": 2003},
    {"id": "matrix3",      "title": "Matrix Revolutions",  "released": 2003},
    {"id": "forrest_gump", "title": "Forrest Gump",        "released": 1994},
    {"id": "castaway",     "title": "Cast Away",           "released": 2000},
    {"id": "davincicode",  "title": "The Da Vinci Code",   "released": 2006},
    {"id": "cloud_atlas",  "title": "Cloud Atlas",         "released": 2012},
    {"id": "apollo13",     "title": "Apollo 13",           "released": 1995},
]

ACTED_IN = [
    ("keanu",    "matrix"),  ("carrie",   "matrix"),  ("laurence", "matrix"),  ("hugo", "matrix"),
    ("keanu",    "matrix2"), ("carrie",   "matrix2"), ("laurence", "matrix2"), ("hugo", "matrix2"),
    ("keanu",    "matrix3"), ("carrie",   "matrix3"), ("laurence", "matrix3"), ("hugo", "matrix3"),
    ("tom_h",    "forrest_gump"), ("gary",  "forrest_gump"), ("robin", "forrest_gump"),
    ("tom_h",    "castaway"),
    ("paul",     "davincicode"), ("audrey", "davincicode"), ("tom_h", "davincicode"),
    ("tom_h",    "cloud_atlas"),
    ("bill_p",   "apollo13"),
]

DIRECTED = [
    ("lilly", "matrix"), ("lana", "matrix"),
    ("lilly", "matrix2"), ("lana", "matrix2"),
    ("lilly", "matrix3"), ("lana", "matrix3"),
    ("robert_z", "forrest_gump"), ("robert_z", "castaway"),
    ("ron", "davincicode"),
    ("lilly", "cloud_atlas"), ("lana", "cloud_atlas"),
    ("ron", "apollo13"),
]

PRODUCED = [
    ("joel", "matrix"), ("joel", "matrix2"), ("joel", "matrix3"),
]


def build_store():
    """Build the graph in DeltaGraphAr and return the GraphStore."""
    repo_dir = tempfile.mkdtemp()
    b = LocalBackend(repo_dir)
    person_vi = VertexInfo(
        label="Person", chunk_size=65_536,
        property_groups=[PropertyGroup([Property("name", "string")], prefix="person_name")],
    )
    movie_vi = VertexInfo(
        label="Movie", chunk_size=65_536,
        property_groups=[PropertyGroup([Property("title", "string"), Property("released", "int32")], prefix="movie_props")],
    )
    gi = GraphInfo(
        name="movies", prefix="",
        vertex_infos=[person_vi, movie_vi],
        edge_infos=[
            EdgeInfo("Person", "ACTED_IN",  "Movie", chunk_size=1_048_576, src_chunk_size=65_536),
            EdgeInfo("Person", "DIRECTED",  "Movie", chunk_size=1_048_576, src_chunk_size=65_536),
            EdgeInfo("Person", "PRODUCED",  "Movie", chunk_size=1_048_576, src_chunk_size=65_536),
        ],
    )
    gs = GraphStore.create(b, gi)
    gs.add_vertices("Person", PEOPLE)
    gs.add_vertices("Movie",  MOVIES)
    gs.add_edges(("Person", "ACTED_IN",  "Movie"), [{"src": s, "dst": d} for s, d in ACTED_IN])
    gs.add_edges(("Person", "DIRECTED",  "Movie"), [{"src": s, "dst": d} for s, d in DIRECTED])
    gs.add_edges(("Person", "PRODUCED",  "Movie"), [{"src": s, "dst": d} for s, d in PRODUCED])
    for etype in [("Person", "ACTED_IN", "Movie"), ("Person", "DIRECTED", "Movie"), ("Person", "PRODUCED", "Movie")]:
        gs.compact(etype)
    return gs


def to_networkx(gs):
    """Read graph back from DeltaGraphAr into a NetworkX DiGraph."""
    G = nx.DiGraph()

    person_ids = [p["id"] for p in PEOPLE]
    movie_ids  = [m["id"] for m in MOVIES]
    name_map   = {p["id"]: p["name"] for p in PEOPLE}
    title_map  = {m["id"]: m["title"] for m in MOVIES}

    for pid in person_ids:
        G.add_node(pid, kind="person", label=name_map[pid])
    for mid in movie_ids:
        G.add_node(mid, kind="movie", label=title_map[mid])

    for pid in person_ids:
        for mid in gs.out_neighbors("Person", pid, ("Person", "ACTED_IN", "Movie")):
            G.add_edge(pid, mid, rel="ACTED_IN")
        for mid in gs.out_neighbors("Person", pid, ("Person", "DIRECTED", "Movie")):
            G.add_edge(pid, mid, rel="DIRECTED")
        for mid in gs.out_neighbors("Person", pid, ("Person", "PRODUCED", "Movie")):
            G.add_edge(pid, mid, rel="PRODUCED")

    return G


def _bipartite_pos(G):
    """Pin persons on the left column, movies on the right — sorted by degree."""
    person_nodes = sorted(
        [n for n, d in G.nodes(data=True) if d["kind"] == "person"],
        key=lambda n: -G.degree(n),
    )
    movie_nodes = sorted(
        [n for n, d in G.nodes(data=True) if d["kind"] == "movie"],
        key=lambda n: -G.degree(n),
    )
    pos = {}
    for i, n in enumerate(person_nodes):
        pos[n] = (-1.0, 1 - i * (2.0 / max(len(person_nodes) - 1, 1)))
    for i, n in enumerate(movie_nodes):
        pos[n] = (1.0, 1 - i * (2.0 / max(len(movie_nodes) - 1, 1)))
    return pos


def draw(G):
    fig, ax = plt.subplots(figsize=(20, 14))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    pos = _bipartite_pos(G)

    person_nodes = [n for n, d in G.nodes(data=True) if d["kind"] == "person"]
    movie_nodes  = [n for n, d in G.nodes(data=True) if d["kind"] == "movie"]

    # Node size proportional to degree so hub movies (The Matrix) are larger
    person_sizes = [300 + G.degree(n) * 120 for n in person_nodes]
    movie_sizes  = [600 + G.degree(n) * 180 for n in movie_nodes]

    nx.draw_networkx_nodes(G, pos, nodelist=person_nodes, node_color="#e94560",
                           node_size=person_sizes, ax=ax, alpha=0.95)
    nx.draw_networkx_nodes(G, pos, nodelist=movie_nodes, node_color="#16527a",
                           node_size=movie_sizes, ax=ax, alpha=0.95)

    edge_styles = {
        "ACTED_IN": ("#a8dadc", 1.6, 0.10),
        "DIRECTED": ("#f4a261", 2.2, 0.20),
        "PRODUCED": ("#95d5b2", 2.2, 0.30),
    }
    for rel, (color, width, rad) in edge_styles.items():
        edges = [(u, v) for u, v, d in G.edges(data=True) if d["rel"] == rel]
        nx.draw_networkx_edges(
            G, pos, edgelist=edges, edge_color=color,
            arrows=True, arrowsize=16, width=width,
            connectionstyle=f"arc3,rad={rad}", ax=ax, alpha=0.75,
        )

    # Person labels: right-aligned just left of node
    person_labels = {n: d["label"] for n, d in G.nodes(data=True) if d["kind"] == "person"}
    movie_labels  = {n: d["label"] for n, d in G.nodes(data=True) if d["kind"] == "movie"}

    for node, label in person_labels.items():
        x, y = pos[node]
        ax.text(x - 0.04, y, label, ha="right", va="center",
                fontsize=8.5, color="white", fontweight="bold")
    for node, label in movie_labels.items():
        x, y = pos[node]
        ax.text(x + 0.04, y, label, ha="left", va="center",
                fontsize=8.5, color="#a8dadc", fontweight="bold")

    # Column headers
    ax.text(-1.0, 1.08, "People", ha="center", fontsize=12,
            color="#e94560", fontweight="bold", transform=ax.transData)
    ax.text( 1.0, 1.08, "Movies", ha="center", fontsize=12,
            color="#a8dadc", fontweight="bold", transform=ax.transData)

    legend = [
        mpatches.Patch(color="#e94560", label="Person"),
        mpatches.Patch(color="#16527a", label="Movie"),
        mpatches.Patch(color="#a8dadc", label="ACTED_IN"),
        mpatches.Patch(color="#f4a261", label="DIRECTED"),
        mpatches.Patch(color="#95d5b2", label="PRODUCED"),
    ]
    ax.legend(handles=legend, loc="lower center", facecolor="#16213e",
              labelcolor="white", fontsize=9, framealpha=0.9,
              ncol=5, bbox_to_anchor=(0.5, -0.02))

    ax.set_title("Neo4j Movie Graph — DeltaGraphAr", color="white",
                 fontsize=15, pad=14, fontweight="bold")
    ax.set_xlim(-1.55, 1.55)
    ax.axis("off")
    plt.tight_layout()
    plt.savefig("examples/movies_graph.png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    print("Saved: examples/movies_graph.png")
    plt.show()


def main():
    print("Building graph in DeltaGraphAr...")
    gs = build_store()
    print(f"  {len(PEOPLE)} persons, {len(MOVIES)} movies, "
          f"{len(ACTED_IN)} ACTED_IN, {len(DIRECTED)} DIRECTED, {len(PRODUCED)} PRODUCED")

    print("Reading back into NetworkX...")
    G = to_networkx(gs)
    print(f"  {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    print("Rendering...")
    draw(G)


if __name__ == "__main__":
    main()
