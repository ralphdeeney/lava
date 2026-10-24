# Working on LAVA

Use the existing checkout; cloud tasks are isolated. Do not create worktrees unless requested.
Read ARCHITECTURE.md and DEVELOPMENT.md first. Keep Phase 00 scoped to foundation.
The modular monolith lives in apps/api/src/lava; the dashboard lives in apps/web.
Run scripts/check.sh after relevant edits. Run the PostgreSQL integration suite and
scripts/smoke.sh for database/container changes; report skipped or unavailable checks explicitly.
Use uv and pnpm with committed locks. Never commit .env, credentials, generated builds, or caches.
API processes must never access the Docker socket. Future privileged adapters run in a worker.
No Kubernetes, billing, autoscaling, or AI agents in this phase.
