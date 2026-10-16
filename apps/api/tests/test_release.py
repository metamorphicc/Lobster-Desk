import subprocess
import zipfile

import pytest

from lobster.ops.release import ReleaseConfig, bundle, safe_source


@pytest.mark.parametrize("changes", [{"mode": "mainnet"}, {"api_host": "0.0.0.0"}, {"worker_instances": 2},
    {"exchange_submission_enabled": True}, {"deployment_enabled": True}, {"token_operations_enabled": True},
    {"jurisdiction": "US"}, {"unknown_override": True}])
def test_local_release_has_no_implicit_activation_switch(changes):
    with pytest.raises(ValueError): ReleaseConfig(**changes)


@pytest.mark.parametrize("name", [".env", ".env.testnet-signer", "data/x.db", "keys/key.pem", "artifacts/a.json", "../key.txt", ".git/config"])
def test_runtime_and_key_paths_never_enter_source_bundle(name):
    assert not safe_source(name)


def test_committed_archive_is_exact_and_dirty_or_forbidden_source_is_refused(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    def git(*args): return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    git("init", "-b", "lobster-desk")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Offline Fixture")
    (root / "apps/api").mkdir(parents=True)
    (root / "apps/api/requirements.lock").write_text("fixture")
    (root / "package-lock.json").write_text("{}")
    git("add", ".")
    git("commit", "-m", "fixture")
    report = bundle(root, tmp_path / "bundle", ReleaseConfig())
    assert report["branch"] == "lobster-desk"
    assert not report["production_verified"]
    with zipfile.ZipFile(tmp_path / "bundle/source.zip") as archive:
        assert archive.read("package-lock.json") == b"{}"
    (root / "uncommitted.txt").write_text("dirty")
    with pytest.raises(ValueError, match="clean"): bundle(root, tmp_path / "dirty", ReleaseConfig())
    (root / "uncommitted.txt").unlink()
    (root / ".env").write_text("fixture only")
    git("add", ".env")
    git("commit", "-m", "forbidden fixture")
    with pytest.raises(ValueError, match="forbidden"): bundle(root, tmp_path / "secret", ReleaseConfig())
