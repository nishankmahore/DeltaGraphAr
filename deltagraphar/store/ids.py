from __future__ import annotations
from typing import Iterable, Optional
import pyarrow as pa

from deltagraphar.format.paths import vid_map_chunk_path
from deltagraphar.format.writer import write_table
from deltagraphar.format.reader import read_table


class IDMap:
    """Logical<->physical vertex ID mapping, stored as chunk-aligned Parquet files.

    Each chunk file covers physical IDs [k*vsize, (k+1)*vsize). Reading always
    scans from the backend, so time-travel is just passing ref= through.
    """

    def __init__(self, backend, label: str, vertex_chunk_size: int):
        self.backend = backend
        self.label = label
        self.vsize = vertex_chunk_size

    def assign(self, logical_ids: Iterable) -> dict[str, int]:
        """Assign sequential physical IDs; persist chunk files. Raises ValueError if already exists."""
        fwd, _ = self._load_all()
        base = len(fwd)

        new_entries: list[tuple[str, int]] = []
        for i, lid in enumerate(logical_ids):
            key = str(lid)
            if key in fwd:
                raise ValueError(f"vertex {key!r} already assigned (phys={fwd[key]})")
            new_entries.append((key, base + i))

        # Group by chunk index and merge with any existing chunk content
        by_chunk: dict[int, list[tuple[str, int]]] = {}
        for lid, phys in new_entries:
            ci = phys // self.vsize
            by_chunk.setdefault(ci, []).append((lid, phys))

        for ci, entries in by_chunk.items():
            self._merge_chunk(ci, entries)

        return {lid: phys for lid, phys in new_entries}

    def resolve(self, logical_ids: Iterable, ref: Optional[str] = None) -> dict[str, int]:
        """Return {str(logical): physical} for all given IDs; KeyError if any unknown."""
        fwd, _ = self._load_all(ref=ref)
        result = {}
        for lid in logical_ids:
            key = str(lid)
            if key not in fwd:
                raise KeyError(key)
            result[key] = fwd[key]
        return result

    def to_logical(self, physical_ids: Iterable[int], ref: Optional[str] = None) -> dict[int, str]:
        """Return {physical: str(logical)} for given physical IDs."""
        _, rev = self._load_all(ref=ref)
        return {p: rev[p] for p in physical_ids if p in rev}

    def _load_all(self, ref=None) -> tuple[dict[str, int], dict[int, str]]:
        fwd: dict[str, int] = {}
        rev: dict[int, str] = {}
        chunk_idx = 0
        while True:
            path = vid_map_chunk_path(self.label, chunk_idx)
            try:
                tbl = read_table(self.backend, path, ref=ref)
                for lid, phys in zip(
                    tbl["vid_logical"].to_pylist(), tbl["vid_physical"].to_pylist()
                ):
                    fwd[lid] = phys
                    rev[phys] = lid
                chunk_idx += 1
            except FileNotFoundError:
                break
        return fwd, rev

    def _merge_chunk(self, chunk_idx: int, new_entries: list[tuple[str, int]]) -> None:
        path = vid_map_chunk_path(self.label, chunk_idx)
        existing_lids: list[str] = []
        existing_phys: list[int] = []
        try:
            tbl = read_table(self.backend, path)
            existing_lids = tbl["vid_logical"].to_pylist()
            existing_phys = tbl["vid_physical"].to_pylist()
        except FileNotFoundError:
            pass

        all_lids = existing_lids + [e[0] for e in new_entries]
        all_phys = existing_phys + [e[1] for e in new_entries]
        write_table(
            self.backend,
            path,
            pa.table({
                "vid_logical": pa.array(all_lids, type=pa.string()),
                "vid_physical": pa.array(all_phys, type=pa.int64()),
            }),
        )
