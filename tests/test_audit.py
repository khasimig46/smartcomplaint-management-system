"""Sprint 3 Task 3 (issue #28): immutable audit log. FR-012, UC-11 step 6, UC-12 step 6, Test Plan TC19."""
import json
from datetime import datetime, timedelta, timezone

import pytest

import routes.complaint_routes as cr
from conftest import complaint_body
from services import audit


@pytest.fixture
def world(app, make_user, login, citizen):
    make_user("agent", email="ag@test.com", name="Ravi", department="Water Department")
    make_user("agent", email="ag2@test.com", name="Meera", department="Water Department")
    make_user("supervisor", email="sup@test.com")
    make_user("admin", email="adm@test.com")
    c = app.test_client()
    hdr = {"citizen": citizen, "agent": login("ag@test.com"), "agent2": login("ag2@test.com"),
           "sup": login("sup@test.com"), "admin": login("adm@test.com")}
    comp = c.post("/submit-complaint", json=complaint_body(category="Water Supply"), headers=citizen).get_json()
    return c, comp, hdr


def move(c, cid, status, headers, note=None):
    return c.patch(f"/complaints/{cid}/status", json={"status": status, "note": note}, headers=headers)


def actions(c, cid, hdr):
    return [e["action"] for e in c.get(f"/complaints/{cid}/audit", headers=hdr["sup"]).get_json()]


# ---------- every action is recorded ----------
def test_full_complaint_lifecycle_is_recorded_with_actor_and_time(world):
    c, comp, hdr = world
    cid = comp["id"]
    agent = comp["assigned_to"]
    other = next(h for h in ("agent", "agent2") if c.get("/auth/me", headers=hdr[h]).get_json()["id"] == agent)
    a = hdr[other]
    c.post("/override-category", json={"complaint_id": cid, "category": "Water Supply"}, headers=hdr["citizen"])
    move(c, cid, "In Progress", a)
    c.post(f"/complaints/{cid}/notes", json={"text": "Valve is cracked"}, headers=a)
    c.post(f"/complaints/{cid}/evidence", data={"files": (__import__("io").BytesIO(b"%PDF-1.4 report"), "report.pdf")},
           headers=a, content_type="multipart/form-data")
    move(c, cid, "Pending Info", a, note="Which house?")
    c.post(f"/complaints/{cid}/reply", json={"text": "House 42"}, headers=hdr["citizen"])
    move(c, cid, "Resolved", a, note="Replaced the valve")
    c.post(f"/complaints/{cid}/feedback", json={"rating": 5}, headers=hdr["citizen"])

    log = c.get(f"/complaints/{cid}/audit", headers=hdr["sup"]).get_json()
    assert [e["action"] for e in log] == [
        "complaint_submitted", "category_overridden", "status_changed", "note_added", "evidence_uploaded",
        "status_changed", "citizen_replied", "status_changed", "complaint_rated"]
    for e in log:
        assert e["actor"] and e["complaint_id"] == cid
        assert datetime.fromisoformat(e["at"]).tzinfo is not None
    assert log[0]["actor"] == comp["citizen_id"] and log[2]["actor"] == agent
    assert log[2]["details"] == {"from_status": "Assigned", "to_status": "In Progress", "note": None}
    assert log[-1]["details"]["rating"] == 5
    assert "Valve is cracked" not in json.dumps(log)          # internal note text is not copied into the log


def test_escalation_is_recorded(world):
    c, comp, hdr = world
    r = c.post(f"/complaints/{comp['id']}/escalate", json={"reason": "Stalled", "department": "Water Department"},
               headers=hdr["sup"])
    assert r.status_code == 200
    e = c.get(f"/complaints/{comp['id']}/audit", headers=hdr["sup"]).get_json()[-1]
    assert e["action"] == "complaint_escalated" and e["details"]["reason"] == "Stalled"


def test_system_actions_are_recorded_as_system(world):
    c, comp, hdr = world
    items = cr._load()
    items[0]["sla"]["due_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    cr._save(items)
    c.post("/sla/check", headers=hdr["sup"])
    e = c.get(f"/complaints/{comp['id']}/audit", headers=hdr["sup"]).get_json()[-1]
    assert e["action"] == "sla_breach" and e["actor"] == "system"


def test_auto_close_is_recorded(world):
    c, comp, hdr = world
    cid = comp["id"]
    a = next(h for h in ("agent", "agent2") if c.get("/auth/me", headers=hdr[h]).get_json()["id"] == comp["assigned_to"])
    move(c, cid, "In Progress", hdr[a]); move(c, cid, "Resolved", hdr[a], note="Done")
    items = cr._load()
    items[0]["history"][-1]["at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    cr._save(items)
    c.post("/sla/check", headers=hdr["sup"])
    e = c.get(f"/complaints/{cid}/audit", headers=hdr["sup"]).get_json()[-1]
    assert e["action"] == "auto_closed" and e["actor"] == "system"


def test_logins_failed_logins_and_admin_actions_are_recorded(world):
    c, _, hdr = world
    c.post("/auth/login", json={"email": "ag@test.com", "password": "wrong-password-123"})
    c.post("/auth/register", json={"name": "New", "email": "new@test.com", "password": "password123"})
    c.post("/auth/users", json={"name": "S2", "email": "s2@test.com", "password": "password123", "role": "supervisor"},
           headers=hdr["admin"])
    c.put("/sla/rules", json={"High": 12}, headers=hdr["admin"])
    log = c.get("/audit", headers=hdr["admin"]).get_json()
    by_action = {e["action"]: e for e in log}                 # newest first, so the latest of each wins
    assert by_action["login"]["actor"]
    failed = by_action["login_failed"]
    assert failed["actor"] is None and failed["details"] == {"email": "ag@test.com"}
    assert "wrong-password-123" not in json.dumps(log)        # passwords never reach the log
    assert by_action["user_registered"]["details"]["role"] == "citizen"
    assert by_action["user_created"]["details"]["role"] == "supervisor"
    assert by_action["sla_rules_changed"]["details"]["changes"] == {"High": 12}


# ---------- access ----------
def test_global_log_is_staff_only_and_filterable(world):
    c, comp, hdr = world
    assert c.get("/audit", headers=hdr["citizen"]).status_code == 403
    assert c.get("/audit", headers=hdr["agent"]).status_code == 403
    assert c.get("/audit").status_code == 401
    only = c.get(f"/audit?complaint={comp['id']}&action=complaint_submitted", headers=hdr["sup"]).get_json()
    assert len(only) == 1 and only[0]["complaint_id"] == comp["id"]
    assert all(e["actor"] == comp["citizen_id"] for e in
               c.get(f"/audit?actor={comp['citizen_id']}", headers=hdr["sup"]).get_json())


def test_complaint_log_access_rules(world):
    c, comp, hdr = world
    cid = comp["id"]
    assigned = next(h for h in ("agent", "agent2") if c.get("/auth/me", headers=hdr[h]).get_json()["id"] == comp["assigned_to"])
    unassigned = "agent2" if assigned == "agent" else "agent"
    assert c.get(f"/complaints/{cid}/audit", headers=hdr[assigned]).status_code == 200
    assert c.get(f"/complaints/{cid}/audit", headers=hdr[unassigned]).status_code == 403
    assert c.get(f"/complaints/{cid}/audit", headers=hdr["citizen"]).status_code == 403
    assert c.get("/complaints/SCMS-00000000-00000/audit", headers=hdr["sup"]).status_code == 404


def test_no_update_or_delete_endpoints(world, app):
    c, _, hdr = world
    for method in ("put", "patch", "delete"):
        assert getattr(c, method)("/audit", headers=hdr["admin"]).status_code == 405
    rules = [r.rule for r in app.url_map.iter_rules() if "audit" in r.rule]
    methods = {m for r in app.url_map.iter_rules() if "audit" in r.rule for m in r.methods}
    assert methods <= {"GET", "HEAD", "OPTIONS"}, rules


# ---------- tamper detection ----------
def test_verify_passes_on_untouched_log(world):
    c, _, hdr = world
    r = c.get("/audit/verify", headers=hdr["admin"])
    assert r.status_code == 200 and r.get_json()["ok"] is True and r.get_json()["entries"] >= 6
    assert c.get("/audit/verify", headers=hdr["sup"]).status_code == 403


def _lines():
    return audit.LOG.read_text().splitlines()


def _write(lines):
    audit.LOG.write_text("\n".join(lines) + "\n")


def test_edited_entry_is_detected(world):
    c, _, hdr = world
    lines = _lines()
    e = json.loads(lines[1]); e["actor"] = "U-someone-else"; lines[1] = json.dumps(e)
    _write(lines)
    r = c.get("/audit/verify", headers=hdr["admin"]).get_json()
    assert r["ok"] is False and r["seq"] == 2 and "modified" in r["problem"]


def test_edited_entry_with_recomputed_hash_breaks_the_chain(world):
    c, _, hdr = world
    lines = _lines()
    e = json.loads(lines[1]); e["actor"] = "U-someone-else"; e["hash"] = audit._digest(e); lines[1] = json.dumps(e)
    _write(lines)
    r = c.get("/audit/verify", headers=hdr["admin"]).get_json()
    assert r["ok"] is False and r["seq"] == 3 and "Chain broken" in r["problem"]


def test_deleted_or_reordered_entries_are_detected(world):
    c, _, hdr = world
    lines = _lines()
    _write(lines[:1] + lines[2:])
    assert c.get("/audit/verify", headers=hdr["admin"]).get_json()["seq"] == 2
    _write([lines[1], lines[0]] + lines[2:])
    assert c.get("/audit/verify", headers=hdr["admin"]).get_json()["ok"] is False
    _write(lines[:2] + ["{not json"] + lines[2:])
    assert "valid JSON" in c.get("/audit/verify", headers=hdr["admin"]).get_json()["problem"]


def test_chain_continues_across_writes(app):
    first = audit.record("test", "U-1", x=1)
    second = audit.record("test", "U-1", x=2)
    assert first["prev_hash"] == audit.GENESIS and second["prev_hash"] == first["hash"] and second["seq"] == 2
    assert audit.verify() == {"ok": True, "entries": 2, "problem": None, "seq": None}


def test_empty_log_verifies(app):
    assert audit.verify()["ok"] is True and audit.entries() == []


def test_audit_page_is_served(app):
    assert b"Audit Log" in app.test_client().get("/audit/view").data
