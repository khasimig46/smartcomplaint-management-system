"""Sprint 3 Task 3: read-only access to the audit log. There are deliberately no update or delete endpoints."""
from flask import Blueprint, g, jsonify, render_template, request

import routes.complaint_routes as cr
from services import audit
from services.auth import STAFF_ROLES, roles_required

bp = Blueprint("audit", __name__)


@bp.get("/audit/view")
def page():
    return render_template("audit.html")


@bp.get("/audit")
@roles_required("supervisor", "admin")
def global_log():
    """Whole log, newest first; filter with ?complaint=, ?actor=, ?action=."""
    a = request.args
    items = audit.entries(a.get("complaint") or None, a.get("actor") or None, a.get("action") or None)
    return jsonify(items[::-1])


@bp.get("/complaints/<cid>/audit")
@roles_required(*STAFF_ROLES)
def complaint_log(cid):
    """Full action history of one complaint, oldest first. Agents only for complaints assigned to them."""
    c = next((x for x in cr._load() if x["id"] == cid), None)
    if not c:
        return jsonify({"error": "Complaint not found"}), 404
    if g.user["role"] == "agent" and c.get("assigned_to") != g.user["id"]:
        return jsonify({"error": "You do not have permission to view this complaint's audit log"}), 403
    return jsonify(audit.entries(complaint_id=cid))


@bp.get("/audit/verify")
@roles_required("admin")
def verify():
    result = audit.verify()
    return jsonify(result), 200 if result["ok"] else 409
