"""Command-line interface for DeltaGraphAr."""
from __future__ import annotations

import argparse
import json
import sys


def _get_backend(args):
    from deltagraphar.versioning.local_backend import LocalBackend
    return LocalBackend(args.repo)


def cmd_log(args):
    b = _get_backend(args)
    commits = b.log()
    if not commits:
        print("(no commits)")
        return
    for c in commits:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(c.timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        meta = f"  {c.metadata}" if c.metadata else ""
        print(f"{c.ref[:8]}  {dt}  {c.message}{meta}")


def cmd_tag(args):
    b = _get_backend(args)
    log = b.log()
    if not log:
        print("error: no commits to tag", file=sys.stderr)
        sys.exit(1)
    ref = log[-1].ref
    b.tag(args.name, ref)
    print(f"tagged {ref[:8]} as {args.name!r}")


def cmd_neighbors(args):
    from deltagraphar.versioning.local_backend import LocalBackend
    from deltagraphar.store.graphstore import GraphStore
    from deltagraphar.format.reader import read_yaml
    from deltagraphar.format.paths import vertex_yaml_path, edge_yaml_path
    from deltagraphar.format.schema import GraphInfo, VertexInfo, EdgeInfo

    b = LocalBackend(args.repo)
    ref = args.ref or None

    etype = tuple(args.etype.split(","))
    if len(etype) != 3:
        print("error: --etype must be 'src,edge,dst'", file=sys.stderr)
        sys.exit(1)

    src_label, et, dst_label = etype
    vi_data = read_yaml(b, vertex_yaml_path(args.label), ref=ref)
    ei_data = read_yaml(b, edge_yaml_path(src_label, et, dst_label), ref=ref)

    vi = VertexInfo(label=vi_data["label"], chunk_size=vi_data["chunk_size"])
    ei = EdgeInfo(
        src_type=ei_data["src_type"],
        edge_type=ei_data["edge_type"],
        dst_type=ei_data["dst_type"],
        chunk_size=ei_data["chunk_size"],
        src_chunk_size=ei_data["src_chunk_size"],
    )
    gi = GraphInfo(name="graph", prefix="", vertex_infos=[vi], edge_infos=[ei])
    gs = GraphStore(b, gi, vertex_chunk_size=vi_data["chunk_size"])
    nbrs = gs.out_neighbors(args.label, args.vertex, etype, ref=ref)
    print(json.dumps(nbrs))


def cmd_compact(args):
    from deltagraphar.versioning.local_backend import LocalBackend
    from deltagraphar.store.graphstore import GraphStore
    from deltagraphar.format.reader import read_yaml
    from deltagraphar.format.paths import vertex_yaml_path, edge_yaml_path
    from deltagraphar.format.schema import GraphInfo, VertexInfo, EdgeInfo

    b = LocalBackend(args.repo)
    etype = tuple(args.etype.split(","))
    if len(etype) != 3:
        print("error: --etype must be 'src,edge,dst'", file=sys.stderr)
        sys.exit(1)

    src_label, et, dst_label = etype
    vi_data = read_yaml(b, vertex_yaml_path(src_label))
    ei_data = read_yaml(b, edge_yaml_path(src_label, et, dst_label))

    vi = VertexInfo(label=vi_data["label"], chunk_size=vi_data["chunk_size"])
    ei = EdgeInfo(
        src_type=ei_data["src_type"],
        edge_type=ei_data["edge_type"],
        dst_type=ei_data["dst_type"],
        chunk_size=ei_data["chunk_size"],
        src_chunk_size=ei_data["src_chunk_size"],
    )
    gi = GraphInfo(name="graph", prefix="", vertex_infos=[vi], edge_infos=[ei])
    gs = GraphStore(b, gi, vertex_chunk_size=vi_data["chunk_size"])

    vchunks = [int(v) for v in args.vchunks.split(",")] if args.vchunks else None
    ref = gs.compact(etype, vchunks=vchunks)
    print(f"compacted → {ref[:8]}")


def main():
    parser = argparse.ArgumentParser(
        prog="deltagraphar",
        description="DeltaGraphAr — versioned property-graph store",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_log = sub.add_parser("log", help="Show commit history")
    p_log.add_argument("--repo", required=True, help="Path to local repo")
    p_log.set_defaults(func=cmd_log)

    p_tag = sub.add_parser("tag", help="Tag the latest commit")
    p_tag.add_argument("--repo", required=True)
    p_tag.add_argument("name", help="Tag name")
    p_tag.set_defaults(func=cmd_tag)

    p_nbr = sub.add_parser("neighbors", help="List out-neighbors of a vertex at a ref")
    p_nbr.add_argument("--repo", required=True)
    p_nbr.add_argument("--label", required=True, help="Vertex label")
    p_nbr.add_argument("--vertex", required=True, help="Logical vertex ID")
    p_nbr.add_argument("--etype", required=True, help="Edge type as 'src,edge,dst'")
    p_nbr.add_argument("--ref", default=None, help="Commit ref or tag (default: HEAD)")
    p_nbr.set_defaults(func=cmd_neighbors)

    p_compact = sub.add_parser("compact", help="Compact delta into ordered CSR")
    p_compact.add_argument("--repo", required=True)
    p_compact.add_argument("--etype", required=True, help="Edge type as 'src,edge,dst'")
    p_compact.add_argument("--vchunks", default=None,
                           help="Comma-separated vchunk indices (default: auto-discover)")
    p_compact.set_defaults(func=cmd_compact)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
