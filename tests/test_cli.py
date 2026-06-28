import json
import subprocess
import sys

from deltagraphar.versioning.local_backend import LocalBackend
from deltagraphar.store.graphstore import GraphStore
from deltagraphar.format.schema import GraphInfo, VertexInfo, EdgeInfo


def _run(args):
    return subprocess.run(
        [sys.executable, "-m", "deltagraphar.cli"] + args,
        capture_output=True, text=True,
    )


def _make_repo(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    vi = VertexInfo(label="v", chunk_size=4)
    ei = EdgeInfo("v", "e", "v", chunk_size=16, src_chunk_size=4)
    gi = GraphInfo(name="g", prefix="", vertex_infos=[vi], edge_infos=[ei])
    gs = GraphStore.create(b, gi, vertex_chunk_size=4)
    gs.add_vertices("v", [{"id": "a"}, {"id": "b"}, {"id": "c"}])
    gs.add_edges(("v", "e", "v"), [{"src": "a", "dst": "b"}, {"src": "a", "dst": "c"}])
    return str(tmp_path / "repo"), gs


def test_log_shows_commits(tmp_path):
    repo, _ = _make_repo(tmp_path)
    result = _run(["log", "--repo", repo])
    assert result.returncode == 0
    assert "create graph" in result.stdout


def test_neighbors_returns_json(tmp_path):
    repo, _ = _make_repo(tmp_path)
    result = _run([
        "neighbors", "--repo", repo,
        "--label", "v", "--vertex", "a", "--etype", "v,e,v",
    ])
    assert result.returncode == 0, result.stderr
    assert sorted(json.loads(result.stdout)) == ["b", "c"]


def test_tag_and_neighbors_at_ref(tmp_path):
    repo, gs = _make_repo(tmp_path)
    ref = gs.backend.log()[-1].ref
    gs.backend.tag("snap1", ref)
    gs.add_edges(("v", "e", "v"), [{"src": "b", "dst": "c"}])

    result = _run([
        "neighbors", "--repo", repo,
        "--label", "v", "--vertex", "b", "--etype", "v,e,v", "--ref", "snap1",
    ])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_compact_cmd(tmp_path):
    repo, _ = _make_repo(tmp_path)
    result = _run(["compact", "--repo", repo, "--etype", "v,e,v", "--vchunks", "0"])
    assert result.returncode == 0, result.stderr
    assert "compacted" in result.stdout


def test_no_command_shows_usage(tmp_path):
    result = _run([])
    assert result.returncode != 0
