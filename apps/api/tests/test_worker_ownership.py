import os
import signal
import subprocess
import sys
import time

from fastapi.testclient import TestClient
import pytest

from lobster.config import Settings
from lobster.execution.settings import TestnetSettings
from lobster.main import create_app
from lobster.ops.worker import worker_lease


def config(tmp_path, enabled=True, name="paper.db"):
    return Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / name}", worker_enabled=enabled)


def client(settings):
    return TestClient(create_app(settings, TestnetSettings(_env_file=None)), base_url="http://127.0.0.1")


def test_duplicate_worker_refused_but_observer_and_other_database_can_start(tmp_path):
    first_config = config(tmp_path)
    duplicate_app = create_app(first_config, TestnetSettings(_env_file=None))
    with client(first_config) as first:
        assert first.get("/api/ready").status_code == 200
        with pytest.raises(ValueError, match="Another local paper worker"):
            with TestClient(duplicate_app, base_url="http://127.0.0.1"):
                pytest.fail("A duplicate worker started")
        assert not hasattr(duplicate_app.state, "runtime")
        with client(config(tmp_path, enabled=False)) as observer:
            assert observer.get("/api/ready").status_code == 503
            assert observer.get("/api/health").status_code == 200
        with client(config(tmp_path, name="other.db")) as independent:
            assert independent.get("/api/ready").status_code == 200
        tasks = list(first.app.state.runtime.tasks.values())
    assert all(task.done() for task in tasks)
    with client(first_config) as restarted:
        assert restarted.get("/api/ready").status_code == 200


def test_startup_failure_releases_ownership(tmp_path, monkeypatch):
    import lobster.main as main
    real_workbench = main.TestnetWorkbench
    def fail(*args):
        raise RuntimeError("Synthetic startup failure")
    monkeypatch.setattr(main, "TestnetWorkbench", fail)
    with pytest.raises(RuntimeError, match="Synthetic startup"):
        with client(config(tmp_path)):
            pytest.fail("Broken startup succeeded")
    monkeypatch.setattr(main, "TestnetWorkbench", real_workbench)
    with client(config(tmp_path)) as restarted:
        assert restarted.get("/api/ready").status_code == 200


def test_lifespan_exception_releases_ownership(tmp_path):
    with pytest.raises(RuntimeError, match="Synthetic lifespan"):
        with client(config(tmp_path)):
            raise RuntimeError("Synthetic lifespan exception")
    with worker_lease(config(tmp_path).database_url):
        pass


def test_canonical_database_alias_uses_same_lock_and_file_presence_is_not_ownership(tmp_path):
    url = f"sqlite:///{tmp_path / 'paper.db'}"
    alias = f"sqlite:///{tmp_path}/./paper.db"
    with worker_lease(url):
        with pytest.raises(ValueError, match="Another local paper worker"):
            with worker_lease(alias):
                pytest.fail("Path alias bypassed ownership")
    assert (tmp_path / "paper.db.paper-worker.lock").is_file()
    with worker_lease(alias):
        pass


@pytest.mark.parametrize("url", ["postgresql://user:synthetic-private@localhost/db", "sqlite:///paper.db?mode=ro"])
def test_unimplemented_leadership_modes_refused_without_echoing_credentials(url):
    with pytest.raises(ValueError, match="leadership") as error:
        worker_lease(url)
    assert "synthetic-private" not in str(error.value)


def test_independent_in_memory_databases_need_no_file_lock():
    with worker_lease("sqlite:///:memory:"), worker_lease("sqlite:///:memory:"):
        pass


def test_os_releases_worker_lock_after_actual_process_is_killed(tmp_path):
    url = f"sqlite:///{tmp_path / 'paper.db'}"
    marker = tmp_path / "child-ready"
    code = """
from pathlib import Path
import os
import sys
from lobster.ops.worker import worker_lease
with worker_lease(sys.argv[1]):
    marker = Path(sys.argv[2])
    staging = marker.with_name('child-ready-staging')
    staging.write_text(str(os.getpid()))
    staging.replace(marker)
    sys.stdin.read()
"""
    child = subprocess.Popen([sys.executable, "-c", code, url, str(marker)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.025)
        assert marker.exists(), "Worker child failed to acquire its local lock"
        owner_pid = int(marker.read_text())
        with pytest.raises(ValueError, match="Another local paper worker"):
            with worker_lease(url):
                pytest.fail("Parent acquired a live child's lock")
        # Windows venv launchers may wrap the actual interpreter. Kill the process
        # that acquired the lock, not just its launcher; do not send it EOF first.
        os.kill(owner_pid, signal.SIGTERM)
        child.wait(timeout=10)
        assert (tmp_path / "paper.db.paper-worker.lock").exists()
        with worker_lease(url):
            pass
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)
