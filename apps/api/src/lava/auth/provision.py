"""Local-only administrative credential provisioning. Never log issued credentials."""

import argparse
import json
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from lava.auth.credentials import issue_credential, revoke_credential
from lava.core.settings import get_settings
from lava.persistence.database import engine_for_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("name")
    create.add_argument("--ttl-hours", type=int, default=24)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("credential_id", type=UUID)
    args = parser.parse_args()
    try:
        settings = get_settings()
        with Session(engine_for_url(settings.database_url.get_secret_value())) as session:
            if args.command == "create":
                user, credential, token = issue_credential(session, args.name, args.ttl_hours)
                # stdout is deliberately the one-time owner delivery channel, not an app log.
                print(
                    json.dumps(
                        {
                            "user_id": user.id,
                            "credential_id": credential.id,
                            "expires_at": credential.expires_at.isoformat(),
                            "token": token,
                        }
                    )
                )
            elif not revoke_credential(session, str(args.credential_id)):
                print("Credential not found")
                return 1
            else:
                print("Credential revoked")
    except (ValueError, SQLAlchemyError):
        print("Credential operation failed; verify configuration, identity and database readiness")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
