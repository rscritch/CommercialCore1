from __future__ import annotations
import hashlib, hmac, os
from fastapi import Request, HTTPException
from sqlalchemy.orm import Session
from .models import User

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${digest.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        alg, iterations, salt_hex, digest_hex = stored.split("$")
        if alg != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False

def current_user(request: Request, db: Session) -> User | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.get(User, uid)

def require_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user or not user.active:
        raise HTTPException(status_code=401)
    return user

def require_role(user: User, *roles: str) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403)
