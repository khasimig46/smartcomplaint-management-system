from datetime import datetime, timedelta, timezone

import pytest

import routes.complaint_routes as cr
from conftest import complaint_body
from services import resolution


@pytest.fixture
def setup(app, make_user, login, citizen):
    make_user("agent", email="ag@test.com", name="Ravi", department="Water Department")
    make_user("supervisor", email="sup@test.com")
    c = app.test_client()
    comp = c.post("/submit-complaint", json=complaint_body(category="Water Supply"), headers=citizen).get_json()
    return c, comp, {"citizen": citizen, "agent": login("ag@test.com"), "sup": login("sup@test.com")}


def move(c, cid, status, headers, note=None):
    return c.patch(f"/complaints/{cid}/status", json={"status": status, "note": note}, headers=headers)


def note(c, cid, headers, text):
    return c.post(f"/complaints/{cid}/notes", json={"text": text}, headers=headers)


def test_agent_queue_sorted_by_sla_with_overdue_on_top(setup, make_user):
    c, comp, hdr = setup
    low = c.post("/submit-complaint", json=complaint_body(category="Water Supply", severity="Low"), headers=hdr["citizen"]).get_json()
    crit = c.post("/submit-complaint", json=complaint_body(category="Water Supply", severity="Critical"), headers=hdr["citizen"]).get_json()
    make_user("agent", email="el@test.com", department="Electricity Department")
    c.post("/submit-complaint", json=complaint_body(category="Electricity"), headers=hdr["citizen"])   # someone else's
    q = c.get("/agent/complaints", headers=hdr["agent"]).get_json()
    assert [i["id"] for i in q] == [crit["id"], comp["id"], low["id"]]
    assert all(i["minutes_left"] > 0 and not i["overdue"] for i in q)

    items = cr._load()
    next(i for i in items if i["id"] == low["id"])["sla"]["due_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    cr._save(items)
    top = c.get("/agent/complaints", headers=hdr["agent"]).get_json()[0]
    assert top["id"] == low["id"] and top["overdue"] is True and top["minutes_left"] < 0


def test_agent_resolves_with_notes_and_citizen_is_notified(setup):
    c, comp, hdr = setup
    move(c, comp["id"], "In Progress", hdr["agent"])
    r = move(c, comp["id"], "Resolved", hdr["agent"], note="Replaced the broken valve")
    assert r.status_code == 200 and r.get_json()["status"] == "Resolved"
    stored = c.get(f"/complaints/{comp['id']}", headers=hdr["citizen"]).get_json()
    assert stored["resolution"]["notes"] == "Replaced the broken valve" and stored["resolution"]["by_name"] == "Ravi"
    assert stored["history"][-1]["note"] == "Replaced the broken valve"
    latest = c.get("/notifications/data", headers=hdr["citizen"]).get_json()["items"][0]
    assert latest["type"] == "resolution" and "Replaced the broken valve" in latest["message"]


def test_resolving_without_notes_is_rejected(setup):
    c, comp, hdr = setup
    move(c, comp["id"], "In Progress", hdr["agent"])
    for blank in (None, "   "):
        r = move(c, comp["id"], "Resolved", hdr["agent"], note=blank)
        assert r.status_code == 400 and "Resolution notes are required" in r.get_json()["error"]
    assert move(c, comp["id"], "Resolved", hdr["sup"]).status_code == 400
    assert move(c, comp["id"], "Resolved", hdr["agent"], note="x" * (resolution.MAX_NOTE + 1)).status_code == 400
    assert c.get(f"/complaints/{comp['id']}", headers=hdr["agent"]).get_json()["status"] == "In Progress"


def test_internal_notes_stored_with_author_and_timestamp(setup):
    c, comp, hdr = setup
    r = note(c, comp["id"], hdr["agent"], "  Visited site, main valve is leaking  ")
    assert r.status_code == 201
    n = r.get_json()
    assert n["id"] == "N1" and n["text"] == "Visited site, main valve is leaking" and n["by_name"] == "Ravi" and n["at"]
    assert note(c, comp["id"], hdr["sup"], "Approved spare parts").get_json()["id"] == "N2"
    assert [x["text"] for x in c.get(f"/complaints/{comp['id']}/notes", headers=hdr["agent"]).get_json()] == \
        ["Visited site, main valve is leaking", "Approved spare parts"]
    assert note(c, comp["id"], hdr["agent"], "").status_code == 400
    assert note(c, comp["id"], hdr["agent"], "x" * (resolution.MAX_NOTE + 1)).status_code == 400


def test_internal_notes_hidden_from_citizen(setup):
    c, comp, hdr = setup
    note(c, comp["id"], hdr["agent"], "Citizen address looks wrong")
    assert "notes" in c.get(f"/complaints/{comp['id']}", headers=hdr["agent"]).get_json()
    assert "notes" not in c.get(f"/complaints/{comp['id']}", headers=hdr["citizen"]).get_json()
    assert "notes" not in c.get("/complaints/mine", headers=hdr["citizen"]).get_json()[0]
    assert c.get(f"/complaints/{comp['id']}/notes", headers=hdr["citizen"]).status_code == 403
    assert note(c, comp["id"], hdr["citizen"], "hi").status_code == 403
    assert c.get("/notifications/data", headers=hdr["citizen"]).get_json()["unread"] == 1   # only "submitted"


def test_only_assigned_agent_can_manage(setup, make_user, login):
    c, comp, hdr = setup
    make_user("agent", email="other@test.com", department="Water Department")
    other = login("other@test.com")
    assert note(c, comp["id"], other, "Not mine").status_code == 403
    assert move(c, comp["id"], "In Progress", other).status_code == 403
    assert c.get("/agent/complaints", headers=other).get_json() == []
    assert note(c, "SCMS-20260101-99999", hdr["agent"], "x").status_code == 404
    assert c.get("/agent/complaints", headers=hdr["sup"]).status_code == 403
    assert c.get("/agent/complaints").status_code == 401
    assert c.get("/agent").status_code == 200


def test_pending_info_question_reaches_citizen(setup):
    c, comp, hdr = setup
    move(c, comp["id"], "In Progress", hdr["agent"])
    assert move(c, comp["id"], "Pending Info", hdr["agent"], note="Please share the nearest landmark").status_code == 200
    latest = c.get("/notifications/data", headers=hdr["citizen"]).get_json()["items"][0]
    assert "Pending Info" in latest["message"] and "nearest landmark" in latest["message"]


def test_reopen_clears_resolution_and_done_items_listed_last(setup):
    c, comp, hdr = setup
    other = c.post("/submit-complaint", json=complaint_body(category="Water Supply", severity="Low"), headers=hdr["citizen"]).get_json()
    move(c, comp["id"], "In Progress", hdr["agent"])
    move(c, comp["id"], "Resolved", hdr["agent"], note="Fixed")
    assert [i["id"] for i in c.get("/agent/complaints", headers=hdr["agent"]).get_json()] == [other["id"]]
    assert [i["id"] for i in c.get("/agent/complaints?all=1", headers=hdr["agent"]).get_json()] == [other["id"], comp["id"]]
    reopened = move(c, comp["id"], "In Progress", hdr["citizen"], note="Still leaking").get_json()
    assert "resolution" not in reopened and [h["status"] for h in reopened["history"]][-2:] == ["Resolved", "In Progress"]


def test_closed_complaint_rejects_notes(setup):
    c, comp, hdr = setup
    move(c, comp["id"], "In Progress", hdr["agent"])
    move(c, comp["id"], "Resolved", hdr["agent"], note="Fixed")
    move(c, comp["id"], "Closed", hdr["citizen"])
    r = note(c, comp["id"], hdr["agent"], "Late note")
    assert r.status_code == 400 and "closed" in r.get_json()["error"]
