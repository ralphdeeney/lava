#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --project apps/api --locked ruff check apps/api scripts/verify_instabox.py scripts/instabox_ci.py scripts/instabox_remote.py
uv run --project apps/api --locked ruff format --check apps/api scripts/verify_instabox.py scripts/instabox_ci.py scripts/instabox_remote.py
uv run --project apps/api --locked pytest apps/api/tests -m 'not integration'
pnpm check
pnpm build
