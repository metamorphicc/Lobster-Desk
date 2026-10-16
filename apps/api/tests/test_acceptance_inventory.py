import pytest

from lobster.ops.acceptance import AcceptanceRecord, inventory, template


def test_unrun_and_observed_evidence_never_grant_execution_or_acceptance(tmp_path):
    record = template()
    assert not inventory(AcceptanceRecord.model_validate(record), tmp_path)["acceptance_verified"]
    record["reviewer"] = "Offline fixture reviewer"
    (tmp_path / "observation.json").write_text('{"fixture":true}', encoding="utf-8")
    for case in record["cases"]:
        case.update(status="observed", files=["observation.json"])
    report = inventory(AcceptanceRecord.model_validate(record), tmp_path)
    assert len(report["files"]) == 1
    assert not report["acceptance_verified"] and not report["execution_authorized"]
    (tmp_path / "observation.json").write_text('{"fixture":false}', encoding="utf-8")
    changed = inventory(AcceptanceRecord.model_validate(record), tmp_path)
    assert changed["files"] != report["files"]


@pytest.mark.parametrize("name", ["../outside.json", "C:/private.json", "nested\\private.json", ".env", "key.pem", "local.sqlite3"])
def test_paths_and_private_material_are_refused(tmp_path, name):
    record = template()
    record["reviewer"] = "Reviewer"
    record["cases"][0].update(status="observed", files=[name])
    for leaf in [".env", "key.pem", "local.sqlite3"]: (tmp_path / leaf).write_text("fixture")
    with pytest.raises((ValueError, FileNotFoundError)):
        inventory(AcceptanceRecord.model_validate(record), tmp_path)


def test_incomplete_cases_and_observations_without_material_fail(tmp_path):
    record = template()
    record["cases"].pop()
    with pytest.raises(ValueError): inventory(AcceptanceRecord.model_validate(record), tmp_path)
    record = template()
    record["cases"][0]["status"] = "observed"
    with pytest.raises(ValueError): inventory(AcceptanceRecord.model_validate(record), tmp_path)
