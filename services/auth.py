"""Issue #1: User accounts, bcrypt password hashing, JWT tokens and RBAC."""
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import bcrypt
import jwt
from flask import current_app, g, jsonify, request

ROLES = ("citizen", "agent", "supervisor", "admin")
STAFF_ROLES = ("agent", "supervisor", "admin")
USERS = Path(__file__).resolve().parent.parent / "data" / "users.json"
TOKEN_HOURS = 8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------- storage (User schema) ----------
def load_users():
    return json.loads(USERS.read_text()) if USERS.exists() else []


def save_users(users):
    USERS.parent.mkdir(parents=True, exist_ok=True)
    USERS.write_text(json.dumps(users, indent=2))


def public(user):
    return {k: v for k, v in user.items() if k != "password_hash"}


def find_user(user_id=None, email=None):
    for u in load_users():
        if (user_id and u["id"] == user_id) or (email and u["email"] == email.lower()):
            return u
    return None


# ---------- registration / login ----------
def create_user(name, email, password, role="citizen", department=None, zone=None):
    name, email = (name or "").strip(), (email or "").strip().lower()
    if not name:
        raise AuthError("Name is required")
    if not EMAIL_RE.match(email):
        raise AuthError("A valid email is required")
    if len(password or "") < 8:
        raise AuthError("Password must be at least 8 characters")
    if role not in ROLES:
        raise AuthError(f"Role must be one of {', '.join(ROLES)}")
    if role == "agent" and not department:
        raise AuthError("Agents must belong to a department")
    users = load_users()
    if any(u["email"] == email for u in users):
        raise AuthError("An account with this email already exists", 409)
    user = {
        "id": "U-" + uuid.uuid4().hex[:8],
        "name": name,
        "email": email,
        "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        "role": role,
        "department": department,
        "zone": zone,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    users.append(user)
    save_users(users)
    return user


def authenticate(email, password):
    user = find_user(email=(email or "").strip())
    if not user or not user["active"] or not bcrypt.checkpw((password or "").encode(), user["password_hash"].encode()):
        raise AuthError("Invalid email or password", 401)
    return user


# ---------- JWT ----------
def issue_token(user):
    now = datetime.now(timezone.utc)
    payload = {"sub": user["id"], "role": user["role"], "iat": now, "exp": now + timedelta(hours=TOKEN_HOURS)}
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def _current_user():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise AuthError("Authentication required", 401)
    try:
        payload = jwt.decode(header[7:], current_app.config["SECRET_KEY"], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError("Session expired, please log in again", 401)
    except jwt.InvalidTokenError:
        raise AuthError("Invalid token", 401)
    user = find_user(user_id=payload["sub"])
    if not user or not user["active"]:
        raise AuthError("Account not found or disabled", 401)
    return user


# ---------- role middleware ----------
def roles_required(*roles):
    """Decorator: require a valid JWT, and (if roles given) one of those roles."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                g.user = _current_user()
            except AuthError as e:
                return jsonify({"error": str(e)}), e.status
            if roles and g.user["role"] not in roles:
                return jsonify({"error": "You do not have permission to do this"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


login_required = roles_required()


def seed_admin_from_env():
    """Create the first admin from ADMIN_EMAIL / ADMIN_PASSWORD if no admin exists."""
    email, password = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
    if email and password and not any(u["role"] == "admin" for u in load_users()):
        create_user("Administrator", email, password, role="admin")
