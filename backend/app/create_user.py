"""Crée l'unique compte de l'application : `python -m app.create_user`.

Il n'existe volontairement aucune inscription publique (le contrat n'en expose pas).
"""
import getpass
import sys
import uuid

from sqlalchemy import text

from app.db import user_scope
from app.defaults import seed_default_statuses
from app.security import hash_password

MIN_PASSWORD_LENGTH = 12


def create_user(email: str, password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Le mot de passe doit contenir au moins {MIN_PASSWORD_LENGTH} caractères")
    user_id = str(uuid.uuid4())
    with user_scope(user_id) as conn:
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, :hash)"),
            {"id": user_id, "email": email.strip().lower(), "hash": hash_password(password)},
        )
        seed_default_statuses(conn, user_id)
    return user_id


def main() -> int:
    email = input("E-mail : ")
    password = getpass.getpass("Mot de passe : ")
    if password != getpass.getpass("Confirmer : "):
        print("Les mots de passe diffèrent.")
        return 1
    try:
        create_user(email, password)
    except ValueError as error:
        print(error)
        return 1
    print("Compte créé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
