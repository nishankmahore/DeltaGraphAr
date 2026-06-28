from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Property:
    name: str
    data_type: str  # int32 | int64 | float32 | float64 | string | bool


@dataclass
class PropertyGroup:
    properties: list[Property]
    file_type: str = "parquet"
    prefix: str = ""  # subdirectory name in chunk paths


@dataclass
class VertexInfo:
    label: str
    chunk_size: int
    property_groups: list[PropertyGroup] = field(default_factory=list)
    version: str = "gar/v1"

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "chunk_size": self.chunk_size,
            "property_groups": [_pg_to_dict(pg) for pg in self.property_groups],
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> VertexInfo:
        return cls(
            label=d["label"],
            chunk_size=d["chunk_size"],
            property_groups=[_pg_from_dict(pg) for pg in d.get("property_groups", [])],
            version=d.get("version", "gar/v1"),
        )


@dataclass
class EdgeInfo:
    src_type: str
    edge_type: str
    dst_type: str
    chunk_size: int
    src_chunk_size: int
    directed: bool = True
    property_groups: list[PropertyGroup] = field(default_factory=list)
    version: str = "gar/v1"
    # adj_lists stored so round-trips are lossless; v1 always emits ordered + unordered by src
    adj_lists: list[dict] = field(default_factory=lambda: [
        {"ordered": True,  "aligned_by": "src", "file_type": "parquet", "prefix": "ordered_by_source"},
        {"ordered": False, "aligned_by": "src", "file_type": "parquet", "prefix": "unordered_by_source"},
    ])

    @property
    def etype(self) -> tuple[str, str, str]:
        return (self.src_type, self.edge_type, self.dst_type)

    def to_dict(self) -> dict:
        return {
            "src_type": self.src_type,
            "edge_type": self.edge_type,
            "dst_type": self.dst_type,
            "directed": self.directed,
            "chunk_size": self.chunk_size,
            "src_chunk_size": self.src_chunk_size,
            "adj_lists": self.adj_lists,
            "property_groups": [_pg_to_dict(pg) for pg in self.property_groups],
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> EdgeInfo:
        return cls(
            src_type=d["src_type"],
            edge_type=d["edge_type"],
            dst_type=d["dst_type"],
            chunk_size=d["chunk_size"],
            src_chunk_size=d["src_chunk_size"],
            directed=d.get("directed", True),
            property_groups=[_pg_from_dict(pg) for pg in d.get("property_groups", [])],
            version=d.get("version", "gar/v1"),
            adj_lists=d.get("adj_lists", [
                {"ordered": True,  "aligned_by": "src", "file_type": "parquet", "prefix": "ordered_by_source"},
                {"ordered": False, "aligned_by": "src", "file_type": "parquet", "prefix": "unordered_by_source"},
            ]),
        )


@dataclass
class GraphInfo:
    name: str
    prefix: str
    vertex_infos: list[VertexInfo] = field(default_factory=list)
    edge_infos: list[EdgeInfo] = field(default_factory=list)
    version: str = "gar/v1"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "prefix": self.prefix,
            "vertices": [f"{vi.label}.vertex.yml" for vi in self.vertex_infos],
            "edges": [f"{ei.src_type}_{ei.edge_type}_{ei.dst_type}.edge.yml" for ei in self.edge_infos],
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict, vertex_infos: list[VertexInfo] | None = None, edge_infos: list[EdgeInfo] | None = None) -> GraphInfo:
        """Reconstruct GraphInfo from manifest dict. Pass pre-loaded vertex/edge infos if available."""
        return cls(
            name=d["name"],
            prefix=d.get("prefix", ""),
            vertex_infos=vertex_infos or [],
            edge_infos=edge_infos or [],
            version=d.get("version", "gar/v1"),
        )


def _pg_to_dict(pg: PropertyGroup) -> dict:
    return {
        "properties": [{"name": p.name, "data_type": p.data_type} for p in pg.properties],
        "file_type": pg.file_type,
        "prefix": pg.prefix,
    }


def _pg_from_dict(d: dict) -> PropertyGroup:
    return PropertyGroup(
        properties=[Property(**p) for p in d["properties"]],
        file_type=d.get("file_type", "parquet"),
        prefix=d.get("prefix", ""),
    )
