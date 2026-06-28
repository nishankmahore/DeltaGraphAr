from __future__ import annotations
import pyarrow as pa
import pyarrow.compute as pc

from deltagraphar.format.paths import adj_list_chunk_path, offset_chunk_path, edge_prop_chunk_path
from deltagraphar.format.reader import read_adj_list, count_rows, read_table
from deltagraphar.format.writer import write_table


def should_compact(backend, etype, vchunk, threshold_ratio, min_rows):
    """True when delta rows exceed max(threshold_ratio * base_rows, min_rows)."""
    src, et, dst = etype
    delta_rows = count_rows(backend, src, et, dst, "unordered_by_source", vchunk)
    if delta_rows == 0:
        return False
    base_rows = count_rows(backend, src, et, dst, "ordered_by_source", vchunk)
    return delta_rows > max(threshold_ratio * base_rows, min_rows)


def compact_vchunk(backend, etype, vchunk, vsize, edge_chunk_size, pg_prefixes):
    """Merge unordered delta into ordered_by_source CSR and recompute offsets.

    Only files under part<vchunk> change. Sort by (src_physical, dst_physical)
    for deterministic layout.
    """
    src, et, dst = etype

    base_adj = read_adj_list(backend, src, et, dst, "ordered_by_source", vchunk)
    delta_adj = read_adj_list(backend, src, et, dst, "unordered_by_source", vchunk)

    if len(base_adj) == 0 and len(delta_adj) == 0:
        return

    parts = [t for t in [base_adj, delta_adj] if len(t) > 0]
    merged = pa.concat_tables(parts) if len(parts) > 1 else parts[0]

    # Sort by (src, dst) — required for CSR correctness and determinism
    sort_indices = pc.sort_indices(
        merged, sort_keys=[("src_physical", "ascending"), ("dst_physical", "ascending")]
    )
    merged = merged.take(sort_indices)

    # Write new ordered adj_list chunks
    _write_chunks(
        backend, merged, edge_chunk_size,
        lambda ci: adj_list_chunk_path(src, et, dst, "ordered_by_source", vchunk, ci),
    )

    # Recompute CSR offset array: offsets[i] = index of first row with src_physical >= vstart+i
    vstart = vchunk * vsize
    src_arr = merged["src_physical"].to_pylist()
    ptr = 0
    offsets: list[int] = []
    for i in range(vsize + 1):
        target = vstart + i
        while ptr < len(src_arr) and src_arr[ptr] < target:
            ptr += 1
        offsets.append(ptr)

    write_table(
        backend,
        offset_chunk_path(src, et, dst, vchunk),
        pa.table({"offset": pa.array(offsets, type=pa.int64())}),
    )

    # Compact edge property groups in tandem, preserving row alignment with adj_list
    for pg_prefix in pg_prefixes:
        base_pg = _read_all_pg_chunks(backend, src, et, dst, "ordered_by_source", pg_prefix, vchunk)
        delta_pg = _read_all_pg_chunks(backend, src, et, dst, "unordered_by_source", pg_prefix, vchunk)
        pg_parts = [t for t in [base_pg, delta_pg] if t is not None and len(t) > 0]
        if pg_parts:
            merged_pg = (pa.concat_tables(pg_parts) if len(pg_parts) > 1 else pg_parts[0]).take(sort_indices)
            _write_chunks(
                backend, merged_pg, edge_chunk_size,
                lambda ci, _p=pg_prefix: edge_prop_chunk_path(src, et, dst, "ordered_by_source", _p, vchunk, ci),
            )

    # Truncate delta: overwrite all existing delta chunks with an empty table
    _truncate_delta(backend, src, et, dst, vchunk, pg_prefixes)


def _write_chunks(backend, table, chunk_size, path_fn):
    n = len(table)
    if n == 0:
        write_table(backend, path_fn(0), table)
        return
    for ci, start in enumerate(range(0, n, chunk_size)):
        write_table(backend, path_fn(ci), table.slice(start, chunk_size))


def _read_all_pg_chunks(backend, src, et, dst, adj_type, pg_prefix, vchunk):
    prefix = f"edge/{src}_{et}_{dst}/{adj_type}/{pg_prefix}/part{vchunk}"
    paths = sorted(backend.list(prefix))
    if not paths:
        return None
    return pa.concat_tables([read_table(backend, p) for p in paths])


def _truncate_delta(backend, src, et, dst, vchunk, pg_prefixes=()):
    """Zero out all unordered delta chunks for this vchunk (adj_list + all property groups)."""
    empty_adj = pa.table({
        "src_physical": pa.array([], type=pa.int64()),
        "dst_physical": pa.array([], type=pa.int64()),
    })
    _zero_prefix(backend, f"edge/{src}_{et}_{dst}/unordered_by_source/adj_list/part{vchunk}", empty_adj)
    for pg_prefix in pg_prefixes:
        # empty table with no columns — schema unknown here, but zero rows is correct sentinel
        _zero_prefix(backend, f"edge/{src}_{et}_{dst}/unordered_by_source/{pg_prefix}/part{vchunk}",
                     pa.table({}))


def _zero_prefix(backend, prefix, empty_table):
    existing = backend.list(prefix)
    if existing:
        for p in existing:
            write_table(backend, p, empty_table)
    else:
        # write a sentinel chunk0 so future compactions see "already cleared"
        write_table(backend, prefix + "/chunk0", empty_table)
