import asyncio
import json

import httpx
import pytest

from lobster.execution.contracts import fingerprint
from lobster.users.rehearsal import SCENARIOS, run_rehearsal


def test_all_user_scenarios_run_without_network_wallet_keys_or_activation(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("The offline rehearsal attempted HTTP")
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    from lobster.execution.settings import SignerSettings
    monkeypatch.setattr(SignerSettings, "__init__", forbidden)
    output = tmp_path / "rehearsal"
    report = asyncio.run(run_rehearsal(output))
    assert report["checks_passed"] and report["offline_fixture"]
    assert {item["scenario"] for item in report["scenarios"]} == set(SCENARIOS)
    assert all(item["production_user_writer_locked"] for item in report["scenarios"])
    assert not report["exchange_writes_attempted"] and not report["funded_acceptance_verified"]
    assert not report["wallet_provider_used"] and not report["execution_authorized"]
    assert report["report_hash"] == fingerprint({key: value for key, value in report.items() if key != "report_hash"})
    stored = json.loads((output / "report.json").read_text())
    assert stored == report
    assert '"proof"' not in json.dumps(report) and '"signature"' not in json.dumps(report)
    with pytest.raises(FileExistsError): asyncio.run(run_rehearsal(output))
