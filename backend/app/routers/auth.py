from fastapi import APIRouter, Form, HTTPException, Header
from typing import Optional
import uuid
import sqlite3
from app.utils.auth import hash_password, verify_password, create_jwt, get_user_from_jwt
from app.database import get_db_connection

router = APIRouter()

@router.post("/register")
async def register_user(username: str = Form(...), password: str = Form(...)):
    pw_hash, salt = hash_password(password)
    user_id = str(uuid.uuid4())
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users(id, username, password_hash, salt, role) VALUES (?, ?, ?, ?, 'user')",
            (user_id, username, pw_hash, salt),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Username already exists")
    conn.close()
    return {"message": "User registered", "user_id": user_id}

@router.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, password_hash, salt FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user_id, password_hash_hex, salt = row
    if not verify_password(password, password_hash_hex, salt):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, role FROM users WHERE id = ?", (user_id,))
    urow = cur.fetchone()
    conn.close()
    token = create_jwt(user_id, urow[0], urow[1])
    return {"message": "Logged in", "token": token}

@router.post("/logout")
async def logout(authorization: Optional[str] = Header(None)):
    return {"message": "Logged out"}


