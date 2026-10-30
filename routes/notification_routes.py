from flask import Blueprint, g, jsonify, render_template, request

from services import notifications
from services.auth import login_required

bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@bp.get("")
def page():
    return render_template("notifications.html")


@bp.get("/data")
@login_required
def inbox():
    items = notifications.for_user(g.user["id"], unread_only=request.args.get("unread") == "1")
    unread = sum(1 for n in notifications.for_user(g.user["id"], unread_only=True))
    return jsonify({"unread": unread, "items": items})


@bp.post("/<nid>/read")
@login_required
def read_one(nid):
    if not notifications.mark_read(g.user["id"], nid):
        return jsonify({"error": "Notification not found or already read"}), 404
    return jsonify({"read": 1})


@bp.post("/read-all")
@login_required
def read_all():
    return jsonify({"read": notifications.mark_read(g.user["id"])})


@bp.get("/preferences")
@login_required
def get_preferences():
    return jsonify(notifications.preferences(g.user))


@bp.put("/preferences")
@login_required
def put_preferences():
    try:
        return jsonify(notifications.update_preferences(g.user["id"], request.get_json(silent=True) or {}))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
