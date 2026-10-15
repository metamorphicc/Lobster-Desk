from copy import deepcopy

import pytest

from lobster.ops.probe import probe_exit_code


def report(ready=True):
    return {"schema": "lobster-local-readiness-v1", "scope": "local-paper-runtime", "diagnostic_only": True,
        "execution_mode": "paper", "production_verified": False, "exchange_execution_verified": False,
        "service_ready": ready, "checks": [{"status": "ok" if ready else "blocked", "label": "Worker responding"}], "alerts": []}


def test_unhealthy_runtime_and_critical_testnet_alert_do_not_exit_healthy():
    assert probe_exit_code(200, report()) == 0
    assert probe_exit_code(503, report(False)) == 1
    assert probe_exit_code(200, report() | {"alerts": [{"severity": "warning", "message": "Operator pause"}]}) == 0
    assert probe_exit_code(200, report() | {"alerts": [{"severity": "critical", "message": "Testnet reconciliation required"}]}) == 1


@pytest.mark.parametrize("change", [{"service_ready": "true"}, {"checks": []}, {"diagnostic_only": False},
    {"production_verified": True}, {"execution_mode": "mainnet"}, {"alerts": [{"severity": "unknown"}]},
    {"checks": [{"label": "Missing", "status": "blocked"}]}])
def test_malformed_or_inconsistent_probe_is_not_healthy(change):
    with pytest.raises(ValueError):
        probe_exit_code(200, report() | deepcopy(change))


def test_http_status_must_match_the_report():
    with pytest.raises(ValueError):
        probe_exit_code(503, report())
    with pytest.raises(ValueError):
        probe_exit_code(200, report(False))
