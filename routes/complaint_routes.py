import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request

from nlp.categorizer import get_categories, suggest_categories

bp = Blueprint("complaints", __name__)
STORE = Path(__file__).resolve().parent.parent / "data" / "complaints_store.json"


def _load():
    return json.loads(STORE.read_text()) if STORE.exists() else []


def _save(items):
    STORE.write_text(json.dumps(items, indent=2))


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
def submit():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Complaint text is required"}), 400
    suggestions = suggest_categories(text)
    complaint = {
        "id": str(uuid.uuid4())[:8],
        "text": text,
        "suggested": suggestions,
        "category": suggestions[0]["category"],
        "overridden": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items = _load()
    items.append(complaint)
    _save(items)
    return jsonify(complaint), 201


@bp.post("/override-category")
def override():
    data = request.get_json(silent=True) or {}
    cid, category = data.get("complaint_id"), data.get("category")
    if category not in get_categories():
        return jsonify({"error": "Invalid category"}), 400
    items = _load()
    for c in items:
        if c["id"] == cid:
            c["category"], c["overridden"] = category, True
            _save(items)
            return jsonify(c)
    return jsonify({"error": "Complaint not found"}), 404


@bp.get("/complaints")
def list_complaints():
    return jsonify(_load())
