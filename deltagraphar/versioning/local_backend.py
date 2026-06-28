from __future__ import annotations
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Optional

from deltagraphar.versioning.backend import Commit, VersioningBackend


class LocalBackend(VersioningBackend):
    """Copy-on-commit backend for unit tests. No Docker required."""

    def __init__(self, root: str):
        self.root = Path(root)
        self.work = self.root / "work"
        self._commits = self.root / ".dga_commits"
        self._tags_path = self.root / ".dga_tags.json"
        self._log_path = self.root / ".dga_log.json"

        self.work.mkdir(parents=True, exist_ok=True)
        self._commits.mkdir(parents=True, exist_ok=True)
        if not self._tags_path.exists():
            self._tags_path.write_text("{}")
        if not self._log_path.exists():
            self._log_path.write_text("[]")

    def write_file(self, path: str, data: bytes) -> None:
        target = self.work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def read_file(self, path: str, ref: Optional[str] = None) -> bytes:
        base = self.work if ref is None else self._commits / self._resolve(ref)
        p = base / path
        if not p.exists():
            raise FileNotFoundError(path)
        return p.read_bytes()

    def list(self, prefix: str, ref: Optional[str] = None) -> list[str]:
        base = self.work if ref is None else self._commits / self._resolve(ref)
        target = base / prefix
        if not target.exists():
            return []
        return [str(p.relative_to(base)) for p in sorted(target.rglob("*")) if p.is_file()]

    def commit(self, message: str, metadata: dict) -> str:
        ts = time.time()
        # incorporate message + ts to avoid collisions on rapid commits
        h = hashlib.sha1(f"{ts:.6f}{message}".encode()).hexdigest()[:16]
        snap = self._commits / h
        if snap.exists():
            shutil.rmtree(snap)
        shutil.copytree(self.work, snap)

        log = self._read_log()
        log.append({"ref": h, "message": message, "timestamp": ts, "metadata": metadata})
        self._log_path.write_text(json.dumps(log, indent=2))
        return h

    def tag(self, name: str, ref: str) -> None:
        tags = json.loads(self._tags_path.read_text())
        tags[name] = self._resolve(ref)
        self._tags_path.write_text(json.dumps(tags))

    def create_branch(self, name: str, source_ref: str) -> None:
        # TODO: v2 — local branching via separate working trees
        raise NotImplementedError("use separate LocalBackend instances for branching in tests")

    def resolve_time(self, ts: float) -> str:
        log = self._read_log()
        candidates = [e for e in log if e["timestamp"] <= ts]
        if not candidates:
            raise ValueError(f"no commits at or before {ts}")
        return candidates[-1]["ref"]

    def log(self) -> list[Commit]:
        return [Commit(**e) for e in self._read_log()]

    def _resolve(self, ref: str) -> str:
        tags = json.loads(self._tags_path.read_text())
        return tags.get(ref, ref)

    def _read_log(self) -> list:
        return json.loads(self._log_path.read_text())
