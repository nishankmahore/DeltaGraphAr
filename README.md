# DeltaGraphAr

A mutable, versioned property-graph store built on the [GraphAr](https://graphar.apache.org) physical layout (chunked Parquet + YAML metadata) with ACID semantics delegated to [LakeFS](https://lakefs.io).

Pure-Python reference implementation. Suitable for graph datasets that evolve over time and need repeatable reads at arbitrary historical snapshots.

## What it does

- Stores vertices and edges as chunked Parquet files following the GraphAr layout spec.
- Appends edges to an unordered "delta" region; CSR-ordered adjacency is built on demand via `compact()`.
- Every mutating operation produces a versioned commit. Any commit ref can be used as a `ref=` argument to read historical state.
- Vertices are identified by arbitrary string logical IDs; the ID map translates to contiguous physical chunk-aligned integers for storage.
- LakeFS backend delegates branching, tagging, and atomic commits to a running LakeFS instance. The local backend (copy-on-commit) requires no external dependencies.

## Install

```bash
pip install -e ".[dev]"
```

Requires Python ≥ 3.10.

## Quickstart

```bash
python examples/quickstart.py
```

Or with LakeFS (requires `docker compose up` first):

```bash
docker compose up -d
python examples/ldbc_snb_tiny_loader.py
```

## API

```python
from deltagraphar.versioning.local_backend import LocalBackend
from deltagraphar.store.graphstore import GraphStore
from deltagraphar.format.schema import GraphInfo, VertexInfo, EdgeInfo

b = LocalBackend("/path/to/repo")
vi = VertexInfo(label="person", chunk_size=65_536)
ei = EdgeInfo("person", "knows", "person", chunk_size=1_048_576, src_chunk_size=65_536)
gi = GraphInfo(name="social", prefix="", vertex_infos=[vi], edge_infos=[ei])

gs = GraphStore.create(b, gi)
gs.add_vertices("person", [{"id": "alice"}, {"id": "bob"}])
gs.add_edges(("person", "knows", "person"), [{"src": "alice", "dst": "bob"}])
gs.compact(("person", "knows", "person"))

neighbors = gs.out_neighbors("person", "alice", ("person", "knows", "person"))
# → ["bob"]

# Time travel
ref = gs.snapshots()[1].ref
old_neighbors = gs.out_neighbors("person", "alice", ("person", "knows", "person"), ref=ref)
```

## CLI

```bash
deltagraphar log --repo /path/to/repo
deltagraphar neighbors --repo /path/to/repo --label person --vertex alice --etype person,knows,person
deltagraphar compact --repo /path/to/repo --etype person,knows,person
deltagraphar tag --repo /path/to/repo v1
```

## Schema evolution

Add a new property group to existing vertices without rewriting existing data:

```python
from deltagraphar.format.schema import PropertyGroup, Property

pg = PropertyGroup([Property("score", "float64")], prefix="person_score")
gs.add_property_group("vertex:person", pg, {"alice": 0.9, "bob": 0.7})
```

## Tests

```bash
pytest
```

51 tests, 2 skipped (LakeFS integration — requires `docker compose up`).

## Benchmarks

```bash
python benchmarks/bench_v1.py --rows 10000 --queries 1000
```

## Architecture

```
GraphStore
├── IDMap          — logical ↔ physical vertex ID, chunk-aligned Parquet
├── compaction.py  — delta→CSR merge, offset sweep, property reorder
└── VersioningBackend (ABC)
    ├── LocalBackend   — copy-on-commit snapshots, no external deps
    └── LakeFSBackend  — atomic commits, branching, tagging via LakeFS API

Physical layout (GraphAr spec)
  vertex/<label>/<pg_prefix>/chunk<k>         — vertex property tables
  vertex/<label>/__vid_map__/chunk<k>         — ID map
  edge/<src>_<et>_<dst>/ordered_by_source/    — CSR adj list + offsets
  edge/<src>_<et>_<dst>/unordered_by_source/  — delta (append-only per vchunk)
```

## Data storage layout

Data is stored as chunked Parquet files under a local repo directory. Using the movie graph as an example (`repo_dir = "/tmp/movies_repo"`):

```
/tmp/movies_repo/
├── work/                                          ← current HEAD (mutable working copy)
│   ├── movies.graph.yml                           ← graph manifest
│   ├── Person.vertex.yml                          ← vertex schema
│   ├── Movie.vertex.yml
│   ├── vertex/
│   │   ├── Person/
│   │   │   ├── person_name/
│   │   │   │   └── chunk0                        ← name column (Parquet)
│   │   │   └── __vid_map__/
│   │   │       └── chunk0                        ← logical↔physical ID map
│   │   └── Movie/
│   │       └── movie_props/
│   │           └── chunk0                        ← title, released columns (Parquet)
│   └── edge/
│       └── Person_ACTED_IN_Movie/
│           ├── Person_ACTED_IN_Movie.edge.yml     ← edge schema
│           ├── ordered_by_source/                 ← CSR (written after compact)
│           │   ├── adj_list/
│           │   │   └── part0/chunk0              ← sorted src/dst pairs (Parquet)
│           │   └── offset/
│           │       └── part0/chunk0              ← CSR offset array (Parquet)
│           └── unordered_by_source/               ← delta (append-only, pre-compact)
│               └── adj_list/
│                   └── part0/chunk0              ← unsorted src/dst pairs (Parquet)
└── snapshots/
    ├── <sha1ref>/                                 ← immutable copy-on-commit snapshot
    ├── <sha1ref>/
    └── ...                                        ← one directory per commit
```

To persist data across runs, replace `tempfile.TemporaryDirectory()` with a fixed path:

```python
repo_dir = "/tmp/movies_repo"
b = LocalBackend(repo_dir)
```

To inspect any chunk file directly:

```python
import pyarrow.parquet as pq
pq.read_table("/tmp/movies_repo/work/vertex/Person/person_name/chunk0").to_pandas()
```

## License

MIT — see [LICENSE](LICENSE)
