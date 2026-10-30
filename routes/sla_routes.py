import threading

from flask import Blueprint, g, jsonify, request

import routes.complaint_routes as cr
from services import notifications, sla
from services.auth import STAFF_ROLES, roles_required

bp = Blueprint("sla", __name__, url_prefix="/sla")
_lock = threading.Lock()


def run_check():
    with _lock:
        items = cr._load()
        new = sla.check(items)
        if new:
            cr._save(items)
            notifications.sla_alerts(new, items)
        return new


@bp.get("/rules")
@roles_required(*STAFF_ROLES)
def get_rules():
    return jsonify(sla.load_rules())


@bp.put("/rules")
@roles_required("admin")
def put_rules():
    try:
        return jsonify(sla.save_rules(request.get_json(silent=True) or {}))
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
