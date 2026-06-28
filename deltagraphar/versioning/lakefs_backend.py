from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

import lakefs
from lakefs_spec import LakeFSFileSystem

from deltagraphar.versioning.backend import Commit, VersioningBackend


class LakeFSBackend(VersioningBackend):
    """LakeFS-backed versioning. Each commit() is an atomic LakeFS commit on the branch.

    Credentials default to the docker-compose dev values in docker-compose.yml.
    """

    def __init__(
        self,
        repo: str,
        branch: str = "main",
        host: str = "http://localhost:8000",
        access_key: str = "AKIAIOSFODNN7EXAMPLE",
        secret_key: str = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    ):
        self.repo = repo
        self.branch = branch
        self._client = lakefs.Client(host=host, username=access_key, password=secret_key)
        self._fs = LakeFSFileSystem(host=host, username=access_key, password=secret_key)
        self._lrepo = lakefs.Repository(repo, client=self._client)

    def write_file(self, path: str, data: bytes) -> None:
        lpath = f"{self.repo}/{self.branch}/{path}"
        with self._fs.open(lpath, "wb") as f:
            f.write(data)

    def read_file(self, path: str, ref: Optional[str] = None) -> bytes:
        r = ref or self.branch
        lpath = f"{self.repo}/{r}/{path}"
        with self._fs.open(lpath, "rb") as f:
            return f.read()

    def list(self, prefix: str, ref: Optional[str] = None) -> list[str]:
        r = ref or self.branch
        lpath = f"{self.repo}/{r}/{prefix}"
        try:
            entries = self._fs.ls(lpath, detail=False, recursive=True)
        except FileNotFoundError:
            return []
        # Strip the "repo/ref/" prefix to get paths relative to graph root
        strip = f"{self.repo}/{r}/"
        return [e.replace(strip, "", 1) for e in entries]

    def commit(self, message: str, metadata: dict) -> str:
        branch_obj = lakefs.Branch(self.repo, self.branch, client=self._client)
        c = branch_obj.commit(
            message=message,
            metadata={k: str(v) for k, v in metadata.items()},
        )
        return c.id

    def tag(self, name: str, ref: str) -> None:
        self._lrepo.tag(name).create(ref)

    def create_branch(self, name: str, source_ref: str) -> None:
        self._lrepo.branch(name).create(source_commit=source_ref)

    def resolve_time(self, ts: float) -> str:
        """Return commit ref of the latest commit at or before Unix timestamp ts."""
        cutoff = datetime.fromtimestamp(ts, tz=timezone.utc)
        for c in self._lrepo.commits(branch=self.branch):
            created = datetime.fromisoformat(c.creation_date)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created <= cutoff:
                return c.id
        raise ValueError(f"no commits at or before {ts}")

    def log(self) -> list[Commit]:
        result = []
        for c in self._lrepo.commits(branch=self.branch):
            created = datetime.fromisoformat(c.creation_date)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            ts = created.timestamp()
            result.append(Commit(
                ref=c.id,
                message=c.message,
                timestamp=ts,
                metadata=c.metadata or {},
            ))
        return list(reversed(result))  # chronological order
