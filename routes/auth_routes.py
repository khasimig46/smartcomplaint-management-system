from flask import Blueprint, g, jsonify, request

from services import auth

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
    return jsonify(auth.public(user)), 201


@bp.post("/login")
def login():
    d = request.get_json(silent=True) or {}
    try:
        user = auth.authenticate(d.get("email"), d.get("password"))
    except auth.AuthError as e:
        return _err(e)
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
    return jsonify(auth.public(user)), 201


@bp.get("/users")
@auth.roles_required("admin")
def list_users():
    return jsonify([auth.public(u) for u in auth.load_users()])
