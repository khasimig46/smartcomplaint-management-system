import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, g, jsonify, request

from nlp.categorizer import get_categories, suggest_categories
from services import complaints as schema
from services.auth import STAFF_ROLES, load_users, login_required, roles_required
from services import sla
from services import status as lifecycle
from services.routing import route
from services.ticket_id import generate_ticket_id

bp = Blueprint("complaints", __name__)
BASE = Path(__file__).resolve().parent.parent
STORE = BASE / "data" / "complaints_store.json"
UPLOADS = BASE / "uploads"


def _load():
    return json.loads(STORE.read_text()) if STORE.exists() else []


def _save(items):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(items, indent=2))


def _can_view(user, complaint):
    return user["role"] in ("supervisor", "admin") or complaint.get("citizen_id") == user["id"] \
        or complaint.get("assigned_to") == user["id"]


@bp.get("/categories")
def categories():
    return jsonify(get_categories())


@bp.post("/suggest-category")
def suggest():
    text = (request.get_json(silent=True) or {}).get("text", "").strip()
    if not text:
        return jsonify({"error": "Complaint text is required"}), 400
    return jsonify(suggest_categories(text))


@bp.post("/submit-complaint")
@roles_required("citizen")
def submit():
    """Accepts multipart/form-data (with images) or JSON (without images)."""
    form = request.form if request.form or request.files else (request.get_json(silent=True) or {})
    images = [(f.filename or "image", f.read()) for f in request.files.getlist("images") if f and f.filename]
    fields, errors = schema.validate(form, images, get_categories())
    if errors:
        return jsonify({"error": "Validation failed", "fields": errors}), 400

    suggestions = suggest_categories(f"{fields['title']}. {fields['description']}")
    category = fields["category"] or suggestions[0]["category"]
    items = _load()
    ticket = generate_ticket_id(c["id"] for c in items)

    saved = []
    if images:
        folder = UPLOADS / ticket
        folder.mkdir(parents=True, exist_ok=True)
        for i, (_, data) in enumerate(images, 1):
            path = folder / f"image{i}{schema.image_extension(data[:8])}"
            path.write_bytes(data)
            saved.append(str(path.relative_to(UPLOADS.parent)))

    complaint = {
        "id": ticket,
        "citizen_id": g.user["id"],
        "title": fields["title"],
        "description": fields["description"],
        "severity": fields["severity"],
        "suggested": suggestions,
        "category": category,
        "overridden": category != suggestions[0]["category"],
        "images": saved,
        "location": fields["location"],
        "zone": fields["zone"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    complaint.update(route(category, load_users(), items, zone=complaint["zone"]))
    lifecycle.start(complaint, g.user["id"])
    sla.assign_deadline(complaint)
    items.append(complaint)
    _save(items)
    return jsonify(complaint), 201


@bp.post("/override-category")
@login_required
def override():
    data = request.get_json(silent=True) or {}
    cid, category = data.get("complaint_id"), data.get("category")
    if category not in get_categories():
        return jsonify({"error": "Invalid category"}), 400
    items = _load()
    for c in items:
        if c["id"] == cid:
            if not _can_view(g.user, c):
                return jsonify({"error": "You do not have permission to do this"}), 403
            c["category"], c["overridden"] = category, True
            others = [o for o in items if o["id"] != cid]
            if c.get("status", "New") in ("New", "Assigned"):  # re-route only before work starts
                c.update(route(category, load_users(), others, zone=c.get("zone")))
                if c["assigned_to"] and c.get("status") == "New":
                    lifecycle.change(c, "Assigned", "system", f"Auto-assigned to {c['assigned_to']}")
            _save(items)
            return jsonify(c)
    return jsonify({"error": "Complaint not found"}), 404


@bp.get("/complaints")
@roles_required(*STAFF_ROLES)
def list_complaints():
    items = _load()
    if g.user["role"] == "agent":
        items = [c for c in items if c.get("assigned_to") == g.user["id"]]
    return jsonify(items)


@bp.get("/complaints/mine")
@roles_required("citizen")
def my_complaints():
    return jsonify([c for c in _load() if c.get("citizen_id") == g.user["id"]])


@bp.get("/complaints/<cid>")
@login_required
def get_complaint(cid):
    for c in _load():
        if c["id"] == cid:
            if not _can_view(g.user, c):
                return jsonify({"error": "You do not have permission to view this complaint"}), 403
            return jsonify(c)
    return jsonify({"error": "Complaint not found"}), 404


@bp.patch("/complaints/<cid>/status")
@login_required
def update_status(cid):
    data = request.get_json(silent=True) or {}
    new_status, note = data.get("status"), (data.get("note") or "").strip() or None
    items = _load()
    for c in items:
        if c["id"] == cid:
            if not lifecycle.allowed_by(g.user, c, new_status):
                return jsonify({"error": "You do not have permission to make this change"}), 403
            try:
                lifecycle.change(c, new_status, g.user["id"], note)
            except lifecycle.TransitionError as e:
                return jsonify({"error": str(e)}), 400
            _save(items)
            return jsonify(c)
    return jsonify({"error": "Complaint not found"}), 404
