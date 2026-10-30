from datetime import datetime, timedelta, timezone

import routes.complaint_routes as cr
from conftest import complaint_body
from services import sla

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


def comp(severity="High", status="Assigned", created=T0, history=None):
    c = {"id": "SCMS-20261102-00001", "severity": severity, "status": status, "assigned_to": "A1",
         "created_at": created.isoformat(), "history": history or []}
    return sla.assign_deadline(c)


def test_deadline_calculated_from_severity_rules():
    assert comp("High")["sla"]["due_at"] == (T0 + timedelta(hours=24)).isoformat()
    assert comp("Critical")["sla"]["due_at"] == (T0 + timedelta(hours=4)).isoformat()


def test_warning_alert_triggers_near_deadline():
    c = comp("High")
    assert sla.check([c], now=T0 + timedelta(hours=10)) == []
    new = sla.check([c], now=T0 + timedelta(hours=23))
    assert len(new) == 1 and new[0]["type"] == "warning" and new[0]["to"] == "A1"
    assert sla.check([c], now=T0 + timedelta(hours=23, minutes=30)) == []   # only once


def test_breach_alert_triggers_after_deadline():
    c = comp("High")
    new = sla.check([c], now=T0 + timedelta(hours=25))
    assert new[0]["type"] == "breach" and new[0]["to"] == "supervisor"
    assert c["sla"]["breached"] is True


def test_resolved_complaints_do_not_alert():
    assert sla.check([comp("High", status="Resolved")], now=T0 + timedelta(hours=30)) == []


def test_violations_and_compliance_tracked():
    on_time = comp("High", status="Resolved", history=[{"status": "Resolved", "at": (T0 + timedelta(hours=5)).isoformat()}])
    late = comp("High", status="Resolved", history=[{"status": "Resolved", "at": (T0 + timedelta(hours=30)).isoformat()}])
    late["id"] = "SCMS-20261102-00002"
    assert sla.compliance([on_time, late]) == 50.0
    assert [v["id"] for v in sla.violations([on_time, late], now=T0 + timedelta(days=3))] == ["SCMS-20261102-00002"]


def test_new_complaint_gets_sla_deadline(app, citizen):
    c = app.test_client().post("/submit-complaint", json=complaint_body(severity="Critical"), headers=citizen).get_json()
    assert c["sla"]["hours"] == 4


def test_admin_configures_rules_others_cannot(app, make_user, login):
    make_user("admin", email="adm@test.com"); make_user("agent", email="ag@test.com", department="Water Department")
    c = app.test_client()
    assert c.put("/sla/rules", json={"High": 12}, headers=login("ag@test.com")).status_code == 403
    assert c.put("/sla/rules", json={"High": 12}, headers=login("adm@test.com")).get_json()["High"] == 12
    assert c.put("/sla/rules", json={"High": -1}, headers=login("adm@test.com")).status_code == 400


def test_alert_endpoints(app, make_user, login, citizen):
    make_user("supervisor", email="sup@test.com")
    c = app.test_client()
    created = c.post("/submit-complaint", json=complaint_body(severity="Critical"), headers=citizen).get_json()
    items = cr._load(); items[0]["sla"]["due_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(); cr._save(items)
    sup = login("sup@test.com")
    alerts = c.get("/sla/alerts", headers=sup).get_json()
    assert alerts[0]["type"] == "breach" and alerts[0]["complaint_id"] == created["id"]
    assert c.get("/sla/violations", headers=sup).get_json()["violations"][0]["id"] == created["id"]
    assert c.get("/sla/alerts", headers=citizen).status_code == 403
