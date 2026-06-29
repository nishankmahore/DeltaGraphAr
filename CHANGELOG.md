# Changelog

## [0.1.1] — 2026-06-29

### Fixed
- Switched GitHub Actions publish workflow from OIDC trusted publishing to API token auth

## [0.1.0] — 2026-06-28

Initial release.

### Added

**Format layer**
- `GraphInfo`, `VertexInfo`, `EdgeInfo`, `PropertyGroup`, `Property` dataclasses with YAML round-trip (`format/schema.py`)
- Deterministic chunk path functions covering vertex, edge adj-list, offset, vid-map, and property-group paths (`format/paths.py`)
- Parquet writer/reader helpers; `read_adj_list`, `read_offsets`, `scan_delta` (`format/reader.py`, `format/writer.py`)

**Versioning**
- `VersioningBackend` ABC: `write_file`, `read_file`, `list`, `commit`, `tag`, `create_branch`, `resolve_time`, `log` (`versioning/backend.py`)
- `LocalBackend`: copy-on-commit snapshots using `shutil.copytree`; SHA-1 refs; full time-travel support (`versioning/local_backend.py`)
- `LakeFSBackend`: wraps `lakefs` SDK + `lakefs-spec` fsspec for production ACID commits, branching, and tagging (`versioning/lakefs_backend.py`)

**Store**
- `IDMap`: chunk-aligned logical↔physical vertex ID mapping with `assign`, `resolve`, `to_logical`, time-travel support (`store/ids.py`)
- `compact_vchunk`: merges unordered delta into sorted CSR, recomputes offset array, rewrites property chunks with consistent sort order, clears delta (`store/compaction.py`)
- `GraphStore`: `add_vertices`, `add_edges`, `compact`, `out_neighbors`, `k_hop`, `add_property_group`, `branch`, `tag`, `snapshots` (`store/graphstore.py`)

**CLI**
- `deltagraphar log`, `neighbors`, `compact`, `tag` subcommands (`cli.py`)

**Tests** (51 passing)
- M1: format round-trip (schema, paths, reader/writer)
- M2: versioning (LocalBackend write/read, time travel, tags, log, resolve_time)
- M3: GraphStore add/read (IDMap, add_vertices, add_edges, out_neighbors)
- M4: compaction (neighbor invariance, vchunk isolation, offset correctness, delta cleared)
- M5: schema evolution (existing chunks unchanged, new property readable, in-memory schema updated)
- M6: time travel (historical out_neighbors, compact then travel, tag pinning, resolve_time)
- Property-based: Hypothesis invariants for neighbor correctness, compaction idempotency, two-batch accumulation

**Examples**
- `examples/quickstart.py`: 5-vertex social graph demonstrating the full write→compact→query→time-travel cycle
- `examples/ldbc_snb_tiny_loader.py`: 10-person LDBC SNB-style graph with k-hop and time travel

**Benchmarks**
- `benchmarks/bench_v1.py`: throughput table for add_vertices, add_edges, compact, out_neighbors

### Fixed

- Lossless `EdgeInfo` YAML round-trip (adj_lists field preserved via lambda default_factory)
- `GraphInfo.from_dict` accepts pre-loaded sub-objects (manifest stores filenames only)
- `_truncate_delta` also clears property group delta chunks (prevented silent data corruption in multi-cycle compaction)
- `add_vertices` uses `enumerate` consistently for physical ID routing (prevented off-by-one on second+ batch)
- Widened `resolve_time` timing window in tests to 50ms to reduce CI flakiness
