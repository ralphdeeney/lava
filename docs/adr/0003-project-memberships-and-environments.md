# ADR0003: Project memberships and environment metadata

Status: accepted for Slice 01.3.

## Authority model

The immutable `projects.owner_id` remains the canonical owner. Migration 0004 backfills an
active Owner membership for every existing project, including quarantined legacy projects;
new projects create their Owner membership in the same transaction. No ownership-transfer
endpoint exists. The application checks an active membership on each request. Project writes
lock the project row before checking authority and changing memberships or resources, so a
revocation and a concurrent resource change have a defined order. Inaccessible project IDs
return the same 404 response as nonexistent IDs.

| Action | Owner | Admin | Developer | Viewer |
| --- | --- | --- | --- | --- |
| Read project, services, environments and active members | Yes | Yes | Yes | Yes |
| Edit/archive project settings | Yes | No | No | No |
| Create/edit/archive services and environment metadata | Yes | Yes | Yes | No |
| Invite, add, change or revoke non-owner members | Yes | Yes | No | No |
| Assign Admin, Developer or Viewer | Yes | Yes | No | No |
| Assign, demote or revoke Owner | No | No | No | No |

Only a separately reviewed ownership-transfer design may change the last row. The frontend
uses role information for controls, while the FastAPI application layer enforces every action.
API bearer clients and browser sessions resolve to the same user and the same project policy.
Archived projects deny writes. Revoked memberships deny subsequent access immediately.

## Invitations

Invitations target an existing, active LAVA user and are accepted or declined only by that
authenticated user. The invitation UUID is a lookup identifier, **not a bearer credential**;
knowing it conveys no authority. Therefore no secret invitation token is issued or stored.
There is no outbound mail delivery or public registration. Invitations expire, can be revoked,
and have single-use status transitions. Only one pending invitation per project and invitee is
allowed. Invitation acceptance checks current authority and membership state within the
project transaction; stale or revoked grants fail. API responses never contain passwords,
session identifiers or sensitive configuration values.

## Environment and service metadata

Environments are project-scoped metadata with unique project slugs and reversible archival.
Archiving cannot delete services or infrastructure. Services from earlier slices retain a
nullable `environment_id`; a composite foreign key prevents assigning an environment from
another project even if an application bug slips through. Configuration stores validated
build-method preference, resource limits, start command, branch reference, desired replicas
and server-managed revision. These fields do not start builds, containers, routing or replicas.
Plaintext environment variables and secrets are excluded from this slice.

Migration 0004 is additive and preserves existing accounts, sessions, projects and services.
Foreign keys restrict physical deletion. Downgrade refuses when collaboration, environment or
non-default service configuration data would be lost. Production must still use separate
least-privilege runtime and migration database roles before public Internet deployment.
