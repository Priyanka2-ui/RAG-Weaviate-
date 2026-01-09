import secrets
import hashlib
import jwt
import datetime
from typing import Optional, Dict, Any
from fastapi import Header, HTTPException
from app.config import settings
from app.database import get_db_connection

def hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, bytes]:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return dk.hex(), salt

def verify_password(password: str, password_hash_hex: str, salt: bytes) -> bool:
    dk_hex, _ = hash_password(password, salt)
    return secrets.compare_digest(dk_hex, password_hash_hex)

def create_jwt(user_id: str, username: str, role: str) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": now + datetime.timedelta(hours=settings.SESSION_TTL_HOURS),
        "iat": now,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGO)

def get_user_from_jwt(token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    try:
        data = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGO])
        user_id = data.get("sub")
        username = data.get("username")
        role = data.get("role")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {"id": row[0], "username": row[1], "role": row[2]}
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

def require_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    user = get_user_from_jwt(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user

