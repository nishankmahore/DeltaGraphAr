from __future__ import annotations
from collections import defaultdict
from typing import Optional

import pyarrow as pa

from deltagraphar.format.paths import (
    adj_list_chunk_path, graph_yaml_path, vertex_yaml_path, edge_yaml_path,
    vertex_chunk_path,
)
from deltagraphar.format.reader import read_adj_list, read_offsets, scan_delta
from deltagraphar.format.writer import write_table, write_yaml
from deltagraphar.format.schema import GraphInfo, PropertyGroup
from deltagraphar.store.ids import IDMap
from deltagraphar.versioning.backend import VersioningBackend, Commit


_PA_TYPES = {
    "int32": pa.int32(), "int64": pa.int64(),
    "float32": pa.float32(), "float64": pa.float64(),
    "string": pa.string(), "bool": pa.bool_(),
}


def _pa_type(name: str):
    t = _PA_TYPES.get(name)
    if t is None:
        raise ValueError(f"unknown data_type {name!r}")
    return t


def _records_to_table(records: list[dict], pg: PropertyGroup) -> pa.Table:
    cols = {
        p.name: pa.array([r.get(p.name) for r in records], type=_pa_type(p.data_type))
        for p in pg.properties
    }
    return pa.table(cols) if cols else pa.table({})


class GraphStore:
    def __init__(
        self,
        backend: VersioningBackend,
        graph_info: GraphInfo,
        branch: str = "main",
        vertex_chunk_size: int = 65_536,
        edge_chunk_size: int = 1_048_576,
        compaction_threshold_ratio: float = 0.5,
        compaction_min_rows: int = 100_000,
    ):
        self.backend = backend
        self.graph_info = graph_info
        self._branch = branch
        self.vsize = vertex_chunk_size
        self.esize = edge_chunk_size
        self.compact_ratio = compaction_threshold_ratio
        self.compact_min = compaction_min_rows
        self._idmaps: dict[str, IDMap] = {}

    @classmethod
    def create(cls, backend: VersioningBackend, graph_info: GraphInfo, **kwargs) -> GraphStore:
        """Write initial YAML metadata and commit. One commit, empty graph."""
        gs = cls(backend, graph_info, **kwargs)
        write_yaml(backend, graph_yaml_path(graph_info.name), graph_info.to_dict())
        for vi in graph_info.vertex_infos:
            write_yaml(backend, vertex_yaml_path(vi.label), vi.to_dict())
        for ei in graph_info.edge_infos:
            write_yaml(backend, edge_yaml_path(*ei.etype), ei.to_dict())
        backend.commit(f"create graph {graph_info.name}", {"op": "create"})
        return gs

    def _idmap(self, label: str) -> IDMap:
        if label not in self._idmaps:
            self._idmaps[label] = IDMap(self.backend, label, self.vsize)
        return self._idmaps[label]

    def add_vertices(self, label: str, records: list[dict]) -> str:
        """Assign physical ids and write vertex + id-map chunks."""
        idmap = self._idmap(label)
        logical_ids = [str(r.get("id", i)) for i, r in enumerate(records)]
        mapping = idmap.assign(logical_ids)

        vi = next(v for v in self.graph_info.vertex_infos if v.label == label)
        for pg in vi.property_groups:
            by_chunk: dict[int, list[dict]] = defaultdict(list)
            for i, r in enumerate(records):
                lid = str(r.get("id", i))
                phys = mapping[lid]
                by_chunk[phys // self.vsize].append(r)
            for ci, chunk_records in by_chunk.items():
                tbl = _records_to_table(chunk_records, pg)
                write_table(self.backend, vertex_chunk_path(label, pg.prefix, ci), tbl)

        return self.backend.commit(
            f"add_vertices {label} +{len(records)}",
            {"op": "add_vertices", "label": label, "count": len(records)},
        )

    def add_edges(self, etype: tuple[str, str, str], records: list[dict]) -> str:
        """Append edges to the unordered delta; call compact() to fold them into CSR."""
        src_label, et, dst_label = etype
        src_map = self._idmap(src_label).resolve(r["src"] for r in records)
        dst_map = self._idmap(dst_label).resolve(r["dst"] for r in records)

        by_chunk: dict[int, list[tuple]] = defaultdict(list)
        for r in records:
            sp = src_map[str(r["src"])]
            dp = dst_map[str(r["dst"])]
            by_chunk[sp // self.vsize].append((sp, dp, r))

        ei = next(e for e in self.graph_info.edge_infos if e.etype == etype)
        for vchunk, rows in by_chunk.items():
            self._append_delta(etype, vchunk, rows, ei)

        return self.backend.commit(
            f"add_edges {et} +{len(records)}",
            {"op": "add_edges", "etype": list(etype), "vchunks": list(by_chunk)},
        )

    def compact(self, etype: tuple[str, str, str], vchunks: Optional[list[int]] = None) -> str:
        """Merge unordered delta into ordered_by_source CSR; recompute offsets.

        If vchunks is None, compacts all vchunks whose delta exceeds the trigger threshold.
        """
        from deltagraphar.store.compaction import should_compact, compact_vchunk

        src, et, dst = etype

        if vchunks is None:
            prefix = f"edge/{src}_{et}_{dst}/unordered_by_source/adj_list"
            all_delta_paths = self.backend.list(prefix)
            seen: set[int] = set()
            for p in all_delta_paths:
                parts = p.split("/")
                part_seg = next((s for s in parts if s.startswith("part")), None)
                if part_seg:
                    seen.add(int(part_seg[4:]))
            vchunks = [
                vc for vc in seen
                if should_compact(self.backend, etype, vc, self.compact_ratio, self.compact_min)
            ]

        ei = next(e for e in self.graph_info.edge_infos if e.etype == etype)
        pg_prefixes = [pg.prefix for pg in ei.property_groups]
        for vc in vchunks:
            compact_vchunk(self.backend, etype, vc, self.vsize, self.esize, pg_prefixes)

        return self.backend.commit(
            f"compact {et} vchunks={vchunks}",
            {"op": "compact", "etype": list(etype), "vchunks": vchunks},
        )

    def add_property_group(self, target: str, pg: PropertyGroup, values: dict) -> str:
        """Write new property chunks aligned to existing vertex data; update in-memory schema.

        target: 'vertex:<label>'
        values: {str(logical_id): value} mapping for the new property
        Existing chunk files are untouched — only new files are written.
        """
        kind, name = target.split(":", 1)
        if kind != "vertex":
            raise NotImplementedError("edge property group evolution — TODO v2")

        label = name
        vi = next(v for v in self.graph_info.vertex_infos if v.label == label)
        idmap = self._idmap(label)
        fwd, _ = idmap._load_all()

        # Group existing vertices by their chunk, in physical-id order within each chunk
        by_chunk: dict[int, list[tuple[str, int]]] = {}
        for lid, phys in sorted(fwd.items(), key=lambda x: x[1]):
            ci = phys // self.vsize
            by_chunk.setdefault(ci, []).append((lid, phys))

        for ci, entries in by_chunk.items():
            col_vals = [values.get(lid) for lid, _ in entries]
            tbl = pa.table({
                p.name: pa.array(col_vals, type=_pa_type(p.data_type))
                for p in pg.properties
            })
            write_table(self.backend, vertex_chunk_path(label, pg.prefix, ci), tbl)

        vi.property_groups.append(pg)
        write_yaml(self.backend, vertex_yaml_path(label), vi.to_dict())

        return self.backend.commit(
            f"add_property_group {target} {pg.prefix}",
            {"op": "add_property_group", "target": target, "pg_prefix": pg.prefix},
        )

    def out_neighbors(
        self, label: str, vid_logical, etype: tuple[str, str, str], ref: Optional[str] = None
    ) -> list:
        """CSR slice union delta scan at snapshot ref (default: latest uncommitted state)."""
        src, et, dst = etype
        idmap = self._idmap(label)
        phys = idmap.resolve([vid_logical], ref=ref)[str(vid_logical)]
        vchunk = phys // self.vsize
        local = phys % self.vsize

        offsets = read_offsets(self.backend, src, et, dst, vchunk, ref=ref)
        base_phys: list[int] = []
        if offsets:
            base_adj = read_adj_list(self.backend, src, et, dst, "ordered_by_source", vchunk, ref=ref)
            base_phys = base_adj[offsets[local]:offsets[local + 1]]["dst_physical"].to_pylist()

        delta_phys = scan_delta(self.backend, src, et, dst, vchunk, phys, ref=ref)

        all_phys = list(set(base_phys + delta_phys))
        rev = self._idmap(dst).to_logical(all_phys, ref=ref)
        return [rev[p] for p in all_phys if p in rev]

    def k_hop(
        self, label: str, vid_logical, etype: tuple[str, str, str], k: int, ref=None
    ) -> set:
        """BFS k hops from vid_logical following etype edges."""
        visited = {str(vid_logical)}
        frontier = {str(vid_logical)}
        for _ in range(k):
            next_frontier = set()
            for v in frontier:
                for nbr in self.out_neighbors(label, v, etype, ref=ref):
                    nbr_s = str(nbr)
                    if nbr_s not in visited:
                        visited.add(nbr_s)
                        next_frontier.add(nbr_s)
            frontier = next_frontier
        return visited - {str(vid_logical)}

    def snapshots(self) -> list[Commit]:
        return self.backend.log()

    def tag(self, name: str, ref: Optional[str] = None) -> None:
        if ref is None:
            ref = self.backend.log()[-1].ref
        self.backend.tag(name, ref)

    def branch(self, name: str, source_ref: Optional[str] = None) -> GraphStore:
        if source_ref is None:
            source_ref = self.backend.log()[-1].ref
        self.backend.create_branch(name, source_ref)
        return GraphStore(
            self.backend, self.graph_info, branch=name,
            vertex_chunk_size=self.vsize, edge_chunk_size=self.esize,
        )

    def _append_delta(self, etype, vchunk, rows, ei):
        src, et, dst = etype
        prefix = f"edge/{src}_{et}_{dst}/unordered_by_source/adj_list/part{vchunk}"
        existing = self.backend.list(prefix)
        chunk_idx = len(existing)

        adj = pa.table({
            "src_physical": pa.array([r[0] for r in rows], type=pa.int64()),
            "dst_physical": pa.array([r[1] for r in rows], type=pa.int64()),
        })
        write_table(
            self.backend,
            adj_list_chunk_path(src, et, dst, "unordered_by_source", vchunk, chunk_idx),
            adj,
        )

        from deltagraphar.format.paths import edge_prop_chunk_path
        for pg in ei.property_groups:
            prop_tbl = _records_to_table([r[2] for r in rows], pg)
            write_table(
                self.backend,
                edge_prop_chunk_path(src, et, dst, "unordered_by_source", pg.prefix, vchunk, chunk_idx),
                prop_tbl,
            )
