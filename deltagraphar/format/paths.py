def vertex_chunk_path(label: str, pg_prefix: str, chunk_idx: int) -> str:
    return f"vertex/{label}/{pg_prefix}/chunk{chunk_idx}"


def vid_map_chunk_path(label: str, chunk_idx: int) -> str:
    return f"vertex/{label}/__vid_map__/chunk{chunk_idx}"


def adj_list_chunk_path(
    src: str, etype: str, dst: str, adj_type: str, vchunk: int, chunk_idx: int
) -> str:
    return f"edge/{src}_{etype}_{dst}/{adj_type}/adj_list/part{vchunk}/chunk{chunk_idx}"


def offset_chunk_path(src: str, etype: str, dst: str, vchunk: int) -> str:
    return f"edge/{src}_{etype}_{dst}/ordered_by_source/offset/part{vchunk}/chunk0"


def edge_prop_chunk_path(
    src: str, etype: str, dst: str,
    adj_type: str, pg_prefix: str, vchunk: int, chunk_idx: int,
) -> str:
    return f"edge/{src}_{etype}_{dst}/{adj_type}/{pg_prefix}/part{vchunk}/chunk{chunk_idx}"


def graph_yaml_path(name: str) -> str:
    return f"{name}.graph.yml"


def vertex_yaml_path(label: str) -> str:
    return f"{label}.vertex.yml"


def edge_yaml_path(src: str, etype: str, dst: str) -> str:
    return f"{src}_{etype}_{dst}.edge.yml"
