from flask import Blueprint, g, jsonify, render_template, request

import routes.complaint_routes as cr
from services import escalation, notifications
from services.auth import load_users, roles_required

bp = Blueprint("escalation", __name__)


@bp.get("/escalations")
def page():
    return render_template("escalations.html")


@bp.get("/escalations/data")
@roles_required("supervisor", "admin")
def data():
    items = cr._load()
    return jsonify({"priority_queue": escalation.priority_queue(items), "stalled": escalation.stalled(items),
                    "teams": escalation.TEAMS, "stalled_hours": escalation.STALLED_HOURS})


@bp.post("/complaints/<cid>/escalate")
@roles_required("supervisor", "admin")
def escalate(cid):
    """JSON {reason, department?}; department defaults to the complaint's current team."""
    d = request.get_json(silent=True) or {}
    items = cr._load()
    c = next((x for x in items if x["id"] == cid), None)
    if not c:
        return jsonify({"error": "Complaint not found"}), 404
    try:
        escalation.escalate(c, g.user, d.get("reason"), d.get("department"), load_users(), items)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    cr._save(items)
    notifications.complaint_escalated(c)
    return jsonify(c)
