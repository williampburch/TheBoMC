import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import func

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import User, create_app, db


def main():
    parser = argparse.ArgumentParser(
        description="Create or update the admin account from environment variables without touching other data."
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Reset the existing admin user's password to ADMIN_PASSWORD if the username already exists.",
    )
    args = parser.parse_args()

    admin_username = (os.getenv("ADMIN_USERNAME") or os.getenv("ADMIN_EMAIL") or "").strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD")

    if not admin_username or not admin_password:
        raise SystemExit("ADMIN_USERNAME/ADMIN_EMAIL and ADMIN_PASSWORD must be set.")

    app = create_app()

    with app.app_context():
        existing_user = User.query.filter(func.lower(User.username) == admin_username).first()

        if existing_user:
            updated = False
            if not existing_user.is_admin:
                existing_user.is_admin = True
                updated = True
            if args.reset_password:
                existing_user.set_password(admin_password)
                updated = True

            if updated:
                db.session.commit()
                print(f"Updated existing admin account: {existing_user.username}")
            else:
                print(f"Admin account already present: {existing_user.username}")
            return

        user = User(username=admin_username, is_admin=True)
        user.set_password(admin_password)
        db.session.add(user)
        db.session.commit()
        print(f"Created admin account: {user.username}")


if __name__ == "__main__":
    main()
