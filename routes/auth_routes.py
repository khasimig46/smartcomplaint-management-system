from flask import Blueprint, g, jsonify, request

from services import audit, auth, notifications, storage
from services.routing import DEPARTMENTS, DEFAULT_DEPARTMENT
from services import sla

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _err(e):
    return jsonify({"error": str(e)}), e.status


@bp.post("/register")
def register():
    """Public self-registration always creates a Citizen account."""
    d = request.get_json(silent=True) or {}
    try:
        user = auth.create_user(d.get("name"), d.get("email"), d.get("password"), role="citizen")
    except auth.AuthError as e:
        return _err(e)
    audit.record("user_registered", user["id"], role="citizen")
    return jsonify(auth.public(user)), 201


@bp.post("/login")
def login():
    d = request.get_json(silent=True) or {}
    try:
        user = auth.authenticate(d.get("email"), d.get("password"))
    except auth.AuthError as e:
        # the attempted email is logged so repeated attacks are visible; the password never is
        audit.record("login_failed", None, email=str(d.get("email") or "")[:254])
        return _err(e)
    audit.record("login", user["id"], role=user["role"])
    return jsonify({"token": auth.issue_token(user), "user": auth.public(user)})


@bp.get("/me")
@auth.login_required
def me():
    return jsonify(auth.public(g.user))


@bp.post("/users")
@auth.roles_required("admin")
def admin_create_user():
    """Admins create Agent / Supervisor / Admin accounts."""
    d = request.get_json(silent=True) or {}
    try:
        user = auth.create_user(d.get("name"), d.get("email"), d.get("password"),
                                role=d.get("role", "citizen"), department=d.get("department"), zone=d.get("zone"))
    except auth.AuthError as e:
        return _err(e)
    audit.record("user_created", g.user["id"], user_id=user["id"], role=user["role"], department=user.get("department"))
    if user["role"] in auth.STAFF_ROLES:
        try:
            notifications.send_email(user["email"], "[SCMS] Welcome to Smart Complaint Management System",
                f"Hello {user['name']}, your {user['role']} account has been created. Sign in using the password provided securely by your administrator. This email never contains a password.")
        except Exception:
            pass
    return jsonify(auth.public(user)), 201


@bp.get("/users")
@auth.roles_required("admin")
def list_users():
    return jsonify([auth.public(u) for u in auth.load_users()])


@bp.get("/users/<user_id>")
@auth.roles_required("admin")
def get_user(user_id):
    user = auth.find_user(user_id=user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify(auth.public(user))


def _reassign_open_complaints(user_id, reason):
    import routes.complaint_routes as cr
    from datetime import datetime, timezone
    with storage.LOCK:
        complaints = cr._load()
        affected = []
        for complaint in complaints:
            if complaint.get("assigned_to") == user_id and complaint.get("status") not in ("Resolved", "Closed"):
                complaint["assigned_to"] = None
                complaint["needs_supervisor"] = True
                if complaint.get("status") == "Assigned":
                    complaint["status"] = "New"
                    complaint.setdefault("history", []).append({
                        "status": "New", "at": datetime.now(timezone.utc).isoformat(),
                        "by": "system", "note": reason
                    })
                affected.append(complaint)
        if affected:
            cr._save(complaints)
            for complaint in affected:
                notifications.notify(notifications.supervisors(), "needs_supervisor",
                    f"Complaint {complaint['id']} needs reassignment: {reason}.", complaint)


@bp.patch("/users/<user_id>")
@auth.roles_required("admin")
@storage.synchronized
def update_user(user_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    allowed = {"name", "email", "role", "department", "zone", "active"}
    unknown = set(data) - allowed
    if unknown:
        return jsonify({"error": "Unsupported fields", "fields": sorted(unknown)}), 400
    users = auth.load_users()
    target = next((u for u in users if u["id"] == user_id), None)
    if not target:
        return jsonify({"error": "User not found"}), 404
    updated = dict(target)
    for key, value in data.items():
        if key == "name":
            if not isinstance(value, str) or not value.strip():
                return jsonify({"error": "Name must be non-empty text"}), 400
            updated[key] = value.strip()
        elif key == "email":
            if not isinstance(value, str) or not auth.EMAIL_RE.match(value.strip()):
                return jsonify({"error": "A valid email is required"}), 400
            email = value.strip().lower()
            if any(u["id"] != user_id and u["email"] == email for u in users):
                return jsonify({"error": "An account with this email already exists"}), 409
            updated[key] = email
        elif key == "role":
            if value not in auth.ROLES:
                return jsonify({"error": "Invalid role"}), 400
            updated[key] = value
        elif key == "department":
            if value is not None and (not isinstance(value, str) or value not in {*DEPARTMENTS.values(), DEFAULT_DEPARTMENT}):
                return jsonify({"error": "Unknown department"}), 400
            updated[key] = value
        elif key == "zone":
            if value is not None and not isinstance(value, str):
                return jsonify({"error": "Zone must be text or null"}), 400
            updated[key] = value.strip() if value else None
        elif key == "active":
            if not isinstance(value, bool):
                return jsonify({"error": "Active must be true or false"}), 400
            updated[key] = value
    if updated["role"] == "agent" and not updated.get("department"):
        return jsonify({"error": "Agents must belong to a department"}), 400
    if target["id"] == g.user["id"] and (not updated["active"] or updated["role"] != "admin"):
        return jsonify({"error": "You cannot deactivate or demote your own admin account"}), 400
    sensitive = any(updated.get(k) != target.get(k) for k in ("email", "role", "active"))
    if sensitive:
        updated["auth_version"] = target.get("auth_version", 0) + 1
    users[users.index(target)] = updated
    auth.save_users(users)
    agent_changed = target.get("role") == "agent" and (
        updated.get("role") != "agent" or not updated.get("active") or
        updated.get("department") != target.get("department"))
    if agent_changed:
        _reassign_open_complaints(user_id, "Agent account deactivated or moved")
    audit.record("user_updated", g.user["id"], user_id=user_id, changed=sorted(data))
    return jsonify(auth.public(updated))


@bp.delete("/users/<user_id>")
@auth.roles_required("admin")
@storage.synchronized
def deactivate_user(user_id):
    users = auth.load_users()
    target = next((u for u in users if u["id"] == user_id), None)
    if not target:
        return jsonify({"error": "User not found"}), 404
    if target["id"] == g.user["id"]:
        return jsonify({"error": "You cannot deactivate your own admin account"}), 400
    target["active"] = False
    target["auth_version"] = target.get("auth_version", 0) + 1
    auth.save_users(users)
    if target.get("role") == "agent":
        _reassign_open_complaints(user_id, "Agent account deactivated")
    audit.record("user_deactivated", g.user["id"], user_id=user_id)
    return jsonify(auth.public(target))
