import io
import yaml
import pyarrow as pa
import pyarrow.parquet as pq


def write_table(backend, path: str, table: pa.Table) -> None:
    buf = io.BytesIO()
    pq.write_table(table, buf)
    backend.write_file(path, buf.getvalue())


def write_yaml(backend, path: str, data: dict) -> None:
    backend.write_file(path, yaml.dump(data, default_flow_style=False).encode())
