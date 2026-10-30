from flask import Blueprint, g, jsonify, render_template, request

import routes.complaint_routes as cr
from services import resolution
from services.auth import STAFF_ROLES, roles_required

bp = Blueprint("resolution", __name__)


def _find(items, cid):
    return next((c for c in items if c["id"] == cid), None)


@bp.get("/agent")
def page():
    return render_template("agent.html")


@bp.get("/agent/complaints")
@roles_required("agent")
def work_queue():
    """Assigned complaints by SLA urgency; ?all=1 also lists resolved and closed ones."""
    return jsonify(resolution.queue(cr._load(), g.user["id"], include_done=request.args.get("all") == "1"))


@bp.post("/complaints/<cid>/notes")
@roles_required(*STAFF_ROLES)
def add_note(cid):
    items = cr._load()
    c = _find(items, cid)
    if not c:
        return jsonify({"error": "Complaint not found"}), 404
    if not resolution.can_manage(g.user, c):
        return jsonify({"error": "You do not have permission to add notes to this complaint"}), 403
    try:
        note = resolution.add_note(c, g.user, (request.get_json(silent=True) or {}).get("text"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    cr._save(items)
    return jsonify(note), 201


@bp.get("/complaints/<cid>/notes")
@roles_required(*STAFF_ROLES)
def list_notes(cid):
    c = _find(cr._load(), cid)
    if not c:
        return jsonify({"error": "Complaint not found"}), 404
    if not cr._can_view(g.user, c):
        return jsonify({"error": "You do not have permission to view this complaint"}), 403
    return jsonify(c.get("notes", []))
