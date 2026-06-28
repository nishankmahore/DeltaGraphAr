from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Commit:
    ref: str
    message: str
    timestamp: float
    metadata: dict


class VersioningBackend(ABC):
    @abstractmethod
    def write_file(self, path: str, data: bytes) -> None: ...

    @abstractmethod
    def read_file(self, path: str, ref: Optional[str] = None) -> bytes: ...

    @abstractmethod
    def list(self, prefix: str, ref: Optional[str] = None) -> list[str]: ...

    @abstractmethod
    def commit(self, message: str, metadata: dict) -> str:
        """Snapshot current state; return an opaque ref string."""

    @abstractmethod
    def tag(self, name: str, ref: str) -> None: ...

    @abstractmethod
    def create_branch(self, name: str, source_ref: str) -> None: ...

    @abstractmethod
    def resolve_time(self, ts: float) -> str:
        """Return the ref of the latest commit at or before timestamp ts."""

    @abstractmethod
    def log(self) -> list[Commit]: ...
