import threading

from flask import Blueprint, g, jsonify, render_template, request

import routes.complaint_routes as cr
from services import audit, feedback, notifications, sla, storage
from nlp.categorizer import get_categories
from services.auth import STAFF_ROLES, roles_required

bp = Blueprint("sla", __name__, url_prefix="/sla")


def run_check():
    """One monitor pass: SLA warning/breach alerts, then auto-close of unrated resolutions (Sprint 3 Task 2)."""
    with storage.LOCK:
        items = cr._load()
        new = sla.check(items)
        closed = feedback.auto_close(items)
        if new or closed:
            cr._save(items)
        for a in new:
            audit.record(f"sla_{a['type']}", audit.SYSTEM, a["complaint_id"], to=a["to"], message=a["message"])
        for c in closed:
            audit.record("auto_closed", audit.SYSTEM, c["id"], reason=c["history"][-1]["note"])
        if new:
            notifications.sla_alerts(new, items)
        for c in closed:
            notifications.status_changed(c, feedback.SYSTEM, c["history"][-1]["note"])
        return new


@bp.get("/admin")
def rules_page():
    """Admin form for SLA rules (UC-10); the data calls below enforce the admin role."""
    return render_template("sla_rules.html")


@bp.get("/rules")
@roles_required(*STAFF_ROLES)
def get_rules():
    return jsonify(sla.load_rules())


@bp.put("/rules")
@roles_required("admin")
def put_rules():
    try:
        updates = request.get_json(silent=True) or {}
        rules = sla.save_rules(updates, categories=get_categories())
        audit.record("sla_rules_changed", g.user["id"], changes=updates)
        return jsonify(rules)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.post("/check")
@roles_required("supervisor", "admin")
def manual_check():
    return jsonify({"new_alerts": run_check()})


@bp.get("/alerts")
@roles_required(*STAFF_ROLES)
def alerts():
    run_check()
    items = cr._load()
    all_alerts = [a for c in items for a in c.get("alerts", [])]
    if g.user["role"] == "agent":
        all_alerts = [a for a in all_alerts if a["to"] == g.user["id"]]
    return jsonify(sorted(all_alerts, key=lambda a: a["at"], reverse=True))


@bp.get("/violations")
@roles_required("supervisor", "admin")
def violations():
    items = cr._load()
    return jsonify({"compliance_percent": sla.compliance(items), "violations": sla.violations(items)})


def start_monitor(app, interval=60):
    """Background thread that checks SLAs every `interval` seconds."""
    def loop():
        while not stop.wait(interval):
            with app.app_context():
                run_check()
    stop = threading.Event()
    threading.Thread(target=loop, daemon=True).start()
    return stop
