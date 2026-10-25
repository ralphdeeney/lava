"""Synthetic privacy regressions; not application acceptance evidence."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

spec = importlib.util.spec_from_file_location(
    "safe_pytest", Path(__file__).resolve().parents[2] / "scripts/run_pytest.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_failure_diagnostics_redact_cookie_password_csrf_and_db():
    values = ["lavabs_" + "a" * 43, "lava_" + "b" * 43, "C" * 43, "d" * 64]
    source = (
        " ".join(values)
        + " password='fixture-password' postgresql+psycopg://user:secret@db/test"
    )
    result = runner.redact(source)
    assert all(value not in result for value in values)
    assert "fixture-password" not in result
    assert "user:secret" not in result


def test_junit_preserves_status_names_and_source_properties(tmp_path):
    raw, safe = tmp_path / "raw.xml", tmp_path / "safe.xml"
    root = ET.Element("testsuite", tests="1", failures="1")
    properties = ET.SubElement(root, "properties")
    ET.SubElement(properties, "property", name="source_commit", value="e" * 40)
    case = ET.SubElement(
        root, "testcase", name="session_security", classname="real.tests"
    )
    ET.SubElement(case, "failure", message="lavabs_" + "a" * 43).text = "C" * 43
    ET.ElementTree(root).write(raw)
    runner.sanitized_junit(raw, safe)
    document = ET.parse(safe)
    assert document.getroot().get("failures") == "1"
    assert document.find("testcase").get("name") == "session_security"
    assert document.find("properties/property").get("value") == "e" * 40
    assert "lavabs_" not in safe.read_text()
    assert safe.stat().st_mode & 0o077 == 0


def test_failed_pytest_stays_failed_and_public_output_is_redacted(
    monkeypatch, tmp_path, capsys
):
    def fail(command, **kwargs):
        raw = Path(
            next(
                arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")
            )
        )
        raw.write_text(
            '<testsuite tests="1" failures="1"><testcase name="failure"><failure /></testcase></testsuite>'
        )
        return SimpleNamespace(returncode=1, stdout="lavabs_" + "a" * 43, stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fail)
    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "runner",
            "--junit",
            str(tmp_path / "safe.xml"),
            "--cwd",
            str(tmp_path),
            "--",
            "tests",
        ],
    )
    assert runner.main() == 1
    assert "lavabs_" not in capsys.readouterr().out
