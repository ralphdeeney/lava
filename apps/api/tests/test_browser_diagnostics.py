"""CI failure visibility must not expose private browser assertion values."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def test_failure_summary_omits_private_diagnostic_values():
    root = Path(__file__).resolve().parents[3]
    spec = spec_from_file_location("browser_verifier", root / "scripts/verify_browser.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    report = {
        "tests": [
            {"name": "logout", "project": "mobile", "status": "failed"},
            {"name": "login", "project": "desktop", "status": "passed"},
        ]
    }
    failures = [
        {
            "name": "logout",
            "project": "mobile",
            "diagnostic": "Timeout: password=private cookie=private",
        }
    ]
    summary = module.public_failure_summary(report, failures)
    assert summary == [{"name": "logout", "project": "mobile", "kind": "timeout"}]
    assert "private" not in str(summary)
