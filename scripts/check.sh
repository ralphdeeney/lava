#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --project apps/api --locked ruff check apps/api
uv run --project apps/api --locked ruff format --check apps/api
uv run --project apps/api --locked pytest apps/api/tests -m 'not integration'
pnpm check
pnpm build
