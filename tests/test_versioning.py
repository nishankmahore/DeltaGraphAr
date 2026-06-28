import time
import pytest
from deltagraphar.versioning.local_backend import LocalBackend


def test_write_read_roundtrip(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    b.write_file("foo/bar.txt", b"hello")
    assert b.read_file("foo/bar.txt") == b"hello"


def test_commit_and_time_travel(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    b.write_file("data.txt", b"v1")
    ref1 = b.commit("first", {"op": "init"})

    b.write_file("data.txt", b"v2")
    ref2 = b.commit("second", {"op": "update"})

    assert b.read_file("data.txt", ref=ref1) == b"v1"
    assert b.read_file("data.txt", ref=ref2) == b"v2"
    assert b.read_file("data.txt") == b"v2"


def test_tags(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    b.write_file("x", b"a")
    ref = b.commit("first", {})
    b.tag("v1", ref)
    b.write_file("x", b"b")
    b.commit("second", {})
    assert b.read_file("x", ref="v1") == b"a"


def test_list_prefix(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    b.write_file("edge/a_e_b/adj_list/part0/chunk0", b"x")
    b.write_file("edge/a_e_b/adj_list/part0/chunk1", b"y")
    b.write_file("vertex/a/prop/chunk0", b"z")
    paths = sorted(b.list("edge/a_e_b/adj_list/part0"))
    assert paths == [
        "edge/a_e_b/adj_list/part0/chunk0",
        "edge/a_e_b/adj_list/part0/chunk1",
    ]


def test_list_at_ref(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    b.write_file("edge/part0/chunk0", b"x")
    ref1 = b.commit("first", {})
    b.write_file("edge/part0/chunk1", b"y")
    b.commit("second", {})

    paths_at_ref1 = sorted(b.list("edge/part0", ref=ref1))
    assert paths_at_ref1 == ["edge/part0/chunk0"]


def test_log(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    b.write_file("f", b"1")
    b.commit("one", {"x": 1})
    b.write_file("f", b"2")
    b.commit("two", {"x": 2})
    log = b.log()
    assert len(log) == 2
    assert log[0].message == "one"
    assert log[1].metadata == {"x": 2}


def test_resolve_time(tmp_path):
    b = LocalBackend(str(tmp_path / "repo"))
    b.write_file("f", b"a")
    t0 = time.time()
    ref1 = b.commit("first", {})
    time.sleep(0.1)
    b.write_file("f", b"b")
    b.commit("second", {})
    # resolve at t0+0.05: after first commit, before second (which is t0+0.1+ε away)
    resolved = b.resolve_time(t0 + 0.05)
    assert b.read_file("f", ref=resolved) == b"a"


# ---------------------------------------------------------------------------
# LakeFS integration tests — require docker compose up; skipped by default
# ---------------------------------------------------------------------------

requires_lakefs = pytest.mark.skipif(
    True,
    reason="requires running LakeFS instance (docker compose up)",
)


@requires_lakefs
def test_lakefs_write_read_roundtrip():
    import lakefs as _lakefs
    from deltagraphar.versioning.lakefs_backend import LakeFSBackend

    client = _lakefs.Client(
        host="http://localhost:8000",
        username="AKIAIOSFODNN7EXAMPLE",
        password="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )
    repo_name = "test-dga-integration"
    try:
        _lakefs.Repository(repo_name, client=client).create(
            storage_namespace=f"local://{repo_name}"
        )
    except Exception:
        pass  # already exists

    b = LakeFSBackend(repo_name, branch="main")
    b.write_file("hello.txt", b"world")
    ref = b.commit("integration test commit", {"op": "test"})
    assert b.read_file("hello.txt", ref=ref) == b"world"


@requires_lakefs
def test_lakefs_time_travel():
    import lakefs as _lakefs
    from deltagraphar.versioning.lakefs_backend import LakeFSBackend

    client = _lakefs.Client(
        host="http://localhost:8000",
        username="AKIAIOSFODNN7EXAMPLE",
        password="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )
    repo_name = "test-dga-tt"
    try:
        _lakefs.Repository(repo_name, client=client).create(
            storage_namespace=f"local://{repo_name}"
        )
    except Exception:
        pass

    b = LakeFSBackend(repo_name, branch="main")
    b.write_file("data.txt", b"v1")
    ref1 = b.commit("first", {})
    b.write_file("data.txt", b"v2")
    b.commit("second", {})
    assert b.read_file("data.txt", ref=ref1) == b"v1"
    assert b.read_file("data.txt") == b"v2"
