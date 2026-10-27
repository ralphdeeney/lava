#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --project apps/api --locked ruff check apps/api scripts/verify_instabox.py scripts/instabox_ci.py scripts/instabox_remote.py scripts/browser_fixture.py scripts/verify_browser.py scripts/run_pytest.py scripts/verify_executor_fixture_builds.py
uv run --project apps/api --locked ruff format --check apps/api scripts/verify_instabox.py scripts/instabox_ci.py scripts/instabox_remote.py scripts/browser_fixture.py scripts/verify_browser.py scripts/run_pytest.py scripts/verify_executor_fixture_builds.py
uv run --project apps/api --locked python scripts/run_pytest.py --cwd apps/api --junit test-results/unit.xml -- tests -m 'not integration'
pnpm check
pnpm build
