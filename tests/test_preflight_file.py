from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from preflight.core import preflight_file, warnings_for

COLUMNS = {"First": "first_name", "Last": "last_name", "Mail": "email", "Phone": "phone",
           "Zip": "postal_code", "Country": "country"}


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "leads.csv").write_text(
        "Lead,First,Last,Mail,Phone,Zip,Country,Notes\n"
        "A-1,Jane,Doe,jane@example.com,(650) 555-1212,94035-1234,US,x\n"
        "A-2,Mrs. Carol,Nguyen Jr.,carol nguyen@example.com,555-0199,94107,,y\n",
        encoding="utf-8",
    )
    return tmp_path


def run(project: Path, **kwargs):
    return preflight_file("data/leads.csv", COLUMNS, root=project, out_dir=project / "out",
                          id_column="Lead", **kwargs)


def test_reply_carries_findings_keyed_by_lead_id_and_no_digest(project):
    reply = run(project, default_region="US")
    assert reply["rows"] == 2 and reply["region_sources"] == {"record": 1, "default_region": 1}
    assert {f["id"] for f in reply["findings"]} == {"A-2"}
    kinds = {(f["platform"], f["field"], f["status"]) for f in reply["findings"]}
    assert ("google", "first_name", "warning") in kinds
    assert ("google", "last_name", "warning") in kinds
    assert ("meta", "email", "warning") in kinds
    assert ("meta", "country", "warning") in kinds
    assert ("meta", "phone", "needs_review") in kinds
    assert not re.search(r"\b[0-9a-f]{64}\b", json.dumps(reply))


def test_upload_file_is_written_by_the_tool_and_keyed_by_id(project):
    reply = run(project, default_region="US")
    upload = json.loads((project / reply["upload_file"]).read_text())
    first = upload["rows"][0]
    assert first["id"] == "A-1"
    assert first["meta"]["zp"] and len(first["meta"]["zp"]) == 64
    assert first["google"]["postal_code"] == "94035-1234"
    assert len(upload["findings"]) == reply["findings_total"]


def test_findings_are_capped_in_the_reply_but_not_in_the_file(project):
    reply = run(project, default_region="US", max_findings=2)
    assert len(reply["findings"]) == 2 and reply["findings_total"] > 2


@pytest.mark.parametrize("path", ["../outside.csv", "/etc/passwd", "data/missing.csv"])
def test_files_outside_the_project_or_missing_are_refused(project, path):
    (project.parent / "outside.csv").write_text("a\n1\n")
    with pytest.raises(ValueError):
        preflight_file(path, COLUMNS, root=project, out_dir=project / "out")


def test_unknown_field_and_missing_column_are_refused(project):
    with pytest.raises(ValueError, match="unknown canonical fields"):
        preflight_file("data/leads.csv", {"Notes": "notes"}, root=project, out_dir=project / "out")
    with pytest.raises(ValueError, match="not in the file header"):
        preflight_file("data/leads.csv", {"Mobile": "phone"}, root=project, out_dir=project / "out")


def test_warnings_do_not_fire_on_clean_values():
    clean = {"first_name": "Mrsa", "last_name": "Junior", "email": "a@example.com", "country": "US"}
    assert warnings_for(clean, "google") == []
    assert warnings_for(clean, "meta") == []
