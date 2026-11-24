"""Reset (or create) a local administrator account.

Supported way to recover admin access; runs inside the API container so it uses the
same database settings as the application:

    docker compose exec api python -m backend.reset_admin            # prompts for the password
    docker compose exec -T api python -m backend.reset_admin --from-env  # uses ADMIN_DEFAULT_PASSWORD

The password must satisfy the application's password policy (12+ characters, upper and
lower case, digit, special character). It is never printed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from .database import SessionLocal
from .models import User, UserRole
from .security import get_password_hash, validate_password_strength


def _read_password(from_env: bool) -> str:
    """Return the new password from the environment or an interactive prompt."""
    if from_env:
        password = os.getenv("ADMIN_DEFAULT_PASSWORD", "")
        if not password:
            raise SystemExit("ADMIN_DEFAULT_PASSWORD is not set.")
        return password
    if not sys.stdin.isatty():
        raise SystemExit("No TTY: run with `docker compose exec` (without -T) or use --from-env.")
    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match.")
    return password


def reset_admin(username: str, password: str) -> str:
    """Set the password of ``username`` (created as a local admin if missing).

    The account is re-activated and forced to the admin role. Returns a short
    description of what was done.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(
                username=username,
                email=f"{username}@labondemand.local",
                full_name="Administrateur",
                auth_provider="local",
            )
            db.add(user)
            action = "created"
        else:
            action = "updated"
        user.hashed_password = get_password_hash(password)
        user.role = UserRole.admin
        user.is_active = True
        db.commit()
        return f"Admin account '{username}' {action}."
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset or create a LabOnDemand admin account.")
    parser.add_argument("--username", default="admin", help="account to reset (default: admin)")
    parser.add_argument(
        "--from-env",
        action="store_true",
        help="use ADMIN_DEFAULT_PASSWORD instead of prompting",
    )
    args = parser.parse_args(argv)

    password = _read_password(args.from_env)
    if not validate_password_strength(password):
        raise SystemExit(
            "Password rejected: 12+ characters with upper case, lower case, digit and special character."
        )
    print(reset_admin(args.username, password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
