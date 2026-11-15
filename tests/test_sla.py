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


# ---------- Sprint 3 Task 6 (issue #31): rules per category and severity ----------
def cat_comp(category, severity="Critical"):
    c = {"id": "X", "category": category, "severity": severity, "status": "Assigned", "created_at": T0.isoformat()}
    return sla.assign_deadline(c)


def test_category_override_applies_only_to_that_category(app):
    sla.save_rules({"by_category": {"Water Supply": {"Critical": 2}}}, categories=["Water Supply", "Roads"])
    assert cat_comp("Water Supply")["sla"]["hours"] == 2
    assert cat_comp("Water Supply")["sla"]["due_at"] == (T0 + timedelta(hours=2)).isoformat()
    assert cat_comp("Roads")["sla"]["hours"] == 4                     # severity default
    assert cat_comp("Water Supply", "High")["sla"]["hours"] == 24     # override is per severity


def test_override_beats_changed_default_and_can_be_removed(app):
    sla.save_rules({"Critical": 6, "by_category": {"Roads": {"Critical": 3}}})
    assert sla.hours_for("Roads", "Critical") == 3 and sla.hours_for("Sanitation", "Critical") == 6
    rules = sla.save_rules({"by_category": {"Roads": {"Critical": None}}})
    assert "Roads" not in rules["by_category"] and sla.hours_for("Roads", "Critical") == 6


def test_unknown_severity_falls_back_to_medium(app):
    assert sla.hours_for("Roads", "Unknown") == 72


def test_admin_sets_category_rule_and_new_complaints_use_it(app, make_user, login, citizen):
    make_user("admin", email="adm@test.com")
    c = app.test_client()
    r = c.put("/sla/rules", json={"by_category": {"Water Supply": {"Critical": 2}}}, headers=login("adm@test.com"))
    assert r.status_code == 200 and r.get_json()["by_category"] == {"Water Supply": {"Critical": 2}}
    assert c.get("/sla/rules", headers=login("adm@test.com")).get_json()["by_category"]["Water Supply"]["Critical"] == 2
    water = c.post("/submit-complaint", json=complaint_body(category="Water Supply", severity="Critical"), headers=citizen)
    roads = c.post("/submit-complaint", json=complaint_body(category="Roads", severity="Critical"), headers=citizen)
    assert water.get_json()["sla"]["hours"] == 2 and roads.get_json()["sla"]["hours"] == 4


def test_invalid_category_rules_are_rejected_and_nothing_is_saved(app, make_user, login):
    make_user("admin", email="adm@test.com")
    c, adm = app.test_client(), login("adm@test.com")
    for bad in ({"by_category": {"Teleportation": {"High": 5}}},        # unknown category
                {"by_category": {"Roads": {"Urgent": 5}}},              # unknown severity
                {"by_category": {"Roads": {"High": 0}}},                # not positive
                {"by_category": {"Roads": {"High": "5"}}},              # not a number
                {"by_category": {"Roads": 5}},                          # wrong shape
                {"by_category": ["Roads"]},
                {"High": 12, "by_category": {"Roads": {"High": -2}}}):  # valid part must not be saved either
        r = c.put("/sla/rules", json=bad, headers=adm)
        assert r.status_code == 400, bad
    rules = c.get("/sla/rules", headers=adm).get_json()
    assert rules["High"] == 24 and rules["by_category"] == {}


def test_only_admin_can_change_category_rules(app, make_user, login):
    make_user("supervisor", email="sup@test.com")
    r = app.test_client().put("/sla/rules", json={"by_category": {"Roads": {"High": 5}}}, headers=login("sup@test.com"))
    assert r.status_code == 403


def test_escalation_uses_category_rule(app, make_user, login, citizen):
    make_user("admin", email="adm@test.com"); make_user("supervisor", email="sup@test.com")
    make_user("agent", email="ag@test.com", department="Water Department")
    c = app.test_client()
    comp = c.post("/submit-complaint", json=complaint_body(category="Water Supply", severity="High"), headers=citizen).get_json()
    c.put("/sla/rules", json={"by_category": {"Water Supply": {"High": 6}}}, headers=login("adm@test.com"))
    assert comp["sla"]["hours"] == 24                                 # existing complaints keep their deadline
    sup = login("sup@test.com")
    r = c.post(f"/complaints/{comp['id']}/escalate", headers=sup,
               json={"reason": "Stalled for days", "department": "Water Department"})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["sla"]["hours"] == 6


def test_sla_rules_page_is_served(app):
    r = app.test_client().get("/sla/admin")
    assert r.status_code == 200 and b"Overrides by category" in r.data
