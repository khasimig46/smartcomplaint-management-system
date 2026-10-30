from flask import Blueprint, g, jsonify, request, send_file

import routes.complaint_routes as cr
from services import evidence
from services.auth import STAFF_ROLES, login_required, roles_required

bp = Blueprint("evidence", __name__)


def _find(items, cid):
    return next((c for c in items if c["id"] == cid), None)


@bp.post("/complaints/<cid>/evidence")
@roles_required(*STAFF_ROLES)
def upload(cid):
    """multipart/form-data with one or more `files`."""
    items = cr._load()
    c = _find(items, cid)
    if not c:
        return jsonify({"error": "Complaint not found"}), 404
    if not evidence.can_upload(g.user, c):
        return jsonify({"error": "You do not have permission to add evidence to this complaint"}), 403
    if c.get("status") == "Closed":
        return jsonify({"error": "Evidence cannot be added to a closed complaint"}), 400
    files = [(f.filename or "file", f.read()) for f in request.files.getlist("files") if f and f.filename]
    error = evidence.validate(files)
    if error:
        return jsonify({"error": error}), 400
    added = evidence.store(c, files, g.user, cr.UPLOADS)
    cr._save(items)
    return jsonify(added), 201


@bp.get("/complaints/<cid>/evidence")
@login_required
def list_evidence(cid):
    c = _find(cr._load(), cid)
    if not c:
        return jsonify({"error": "Complaint not found"}), 404
    if not cr._can_view(g.user, c):
        return jsonify({"error": "You do not have permission to view this complaint"}), 403
    return jsonify(c.get("evidence", []))


@bp.get("/complaints/<cid>/evidence/<eid>")
@login_required
def download(cid, eid):
    c = _find(cr._load(), cid)
    if not c:
        return jsonify({"error": "Complaint not found"}), 404
    if not cr._can_view(g.user, c):
        return jsonify({"error": "You do not have permission to view this complaint"}), 403
    entry = next((e for e in c.get("evidence", []) if e["id"] == eid), None)
    if not entry or not (cr.UPLOADS.parent / entry["path"]).is_file():
        return jsonify({"error": "Evidence not found"}), 404
    return send_file(cr.UPLOADS.parent / entry["path"], mimetype=entry["content_type"],
                     as_attachment=True, download_name=entry["filename"])
