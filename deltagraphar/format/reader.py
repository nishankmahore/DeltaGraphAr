import io
import yaml
import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.compute as pc

from deltagraphar.format.paths import offset_chunk_path


def read_table(backend, path: str, ref=None) -> pa.Table:
    data = backend.read_file(path, ref=ref)
    return pq.read_table(io.BytesIO(data))


def read_yaml(backend, path: str, ref=None) -> dict:
    return yaml.safe_load(backend.read_file(path, ref=ref))


def read_adj_list(
    backend, src: str, etype: str, dst: str, adj_type: str, vchunk: int, ref=None
) -> pa.Table:
    """Concatenate all chunk files for one (adj_type, vchunk) partition."""
    prefix = f"edge/{src}_{etype}_{dst}/{adj_type}/adj_list/part{vchunk}"
    paths = sorted(backend.list(prefix, ref=ref))
    if not paths:
        return pa.table({
            "src_physical": pa.array([], type=pa.int64()),
            "dst_physical": pa.array([], type=pa.int64()),
        })
    return pa.concat_tables([read_table(backend, p, ref=ref) for p in paths])


def read_offsets(backend, src: str, etype: str, dst: str, vchunk: int, ref=None) -> list[int]:
    """Read the CSR offset array for a vchunk; returns [] if not yet compacted."""
    path = offset_chunk_path(src, etype, dst, vchunk)
    try:
        tbl = read_table(backend, path, ref=ref)
        return tbl["offset"].to_pylist()
    except FileNotFoundError:
        return []


def scan_delta(
    backend, src: str, etype: str, dst: str, vchunk: int, src_physical: int, ref=None
) -> list[int]:
    """Return dst_physical list from unordered delta where src_physical matches."""
    delta = read_adj_list(backend, src, etype, dst, "unordered_by_source", vchunk, ref=ref)
    if len(delta) == 0:
        return []
    mask = pc.equal(delta["src_physical"], src_physical)
    return delta.filter(mask)["dst_physical"].to_pylist()


def count_rows(
    backend, src: str, etype: str, dst: str, adj_type: str, vchunk: int, ref=None
) -> int:
    tbl = read_adj_list(backend, src, etype, dst, adj_type, vchunk, ref=ref)
    return len(tbl)
