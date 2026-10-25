"""Preserve pytest exit codes while redacting credentials from public logs and JUnit."""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET


def redact(value: str) -> str:
    value = re.sub(
        r"(?<![A-Za-z0-9_])(?:lavabs_|lava_)[A-Za-z0-9_-]+", "[REDACTED]", value
    )
    value = re.sub(
        r"(?i)postgres(?:ql)?(?:\+psycopg)?://[^\s'\"<>]+", "[REDACTED-DB]", value
    )
    value = re.sub(r"\$argon2(?:id|i|d)\$[^\s'\"<>]+", "[REDACTED-HASH]", value)
    value = re.sub(
        r"(?i)([\"']?password[\"']?\s*[:=]\s*)([\"'])(.*?)\2",
        r'\1"[REDACTED]"',
        value,
    )
    # Random fixture passwords are token_urlsafe(32), and CSRF material is64hex.
    value = re.sub(
        r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])", "[REDACTED]", value
    )
    return re.sub(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", "[REDACTED]", value)


def sanitized_junit(source: Path, destination: Path) -> None:
    document = ET.parse(source)
    for element in document.iter():
        if element.tag in {"failure", "error", "system-out", "system-err"}:
            if element.text:
                element.text = redact(element.text)
            for key, value in element.attrib.items():
                element.set(key, redact(value))
    destination.parent.mkdir(parents=True, exist_ok=True)
    document.write(destination, encoding="utf-8", xml_declaration=True)
    destination.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    extra = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
    target = args.junit.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Raw reports never reach the published path; remove them after sanitization.
        with tempfile.TemporaryDirectory(prefix="lava-pytest-") as directory:
            raw = Path(directory) / "raw.xml"
            result = subprocess.run(
                [sys.executable, "-m", "pytest", *extra, "--junitxml=" + str(raw)],
                cwd=args.cwd,
                capture_output=True,
                text=True,
                timeout=900,
            )
            print(redact(result.stdout), end="")
            print(redact(result.stderr), end="", file=sys.stderr)
            if raw.exists():
                sanitized_junit(raw, target)
            elif result.returncode == 0:
                print("Pytest returned no execution report", file=sys.stderr)
                return 1
            return result.returncode
    except subprocess.TimeoutExpired:
        print(
            "Pytest timed out; credential-bearing diagnostics withheld", file=sys.stderr
        )
        return 124
    except (OSError, ET.ParseError):
        print("Pytest evidence could not be published safely", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
