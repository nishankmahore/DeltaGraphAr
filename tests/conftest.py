import pytest


@pytest.fixture
def tmp_backend(tmp_path):
    from deltagraphar.versioning.local_backend import LocalBackend
    return LocalBackend(str(tmp_path / "repo"))
