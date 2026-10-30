from datetime import datetime, timedelta, timezone

import pytest

import routes.complaint_routes as cr
from conftest import complaint_body
from services import escalation, sla


@pytest.fixture
def setup(app, make_user, login, citizen):
    ravi = make_user("agent", email="ravi@test.com", name="Ravi", department="Water Department")
    asha = make_user("agent", email="asha@test.com", name="Asha", department="Water Department")
    make_user("supervisor", email="sup@test.com", name="Meera")
    c = app.test_client()
    comp = c.post("/submit-complaint", json=complaint_body(category="Water Supply"), headers=citizen).get_json()
    hdr = {"citizen": citizen, "ravi": login("ravi@test.com"), "asha": login("asha@test.com"), "sup": login("sup@test.com")}
    return c, comp, hdr, ravi, asha


def escalate(c, cid, headers, reason="No response from field team", department=None):
    return c.post(f"/complaints/{cid}/escalate", json={"reason": reason, "department": department}, headers=headers)


def edit(cid, fn):
    items = cr._load()
    fn(next(i for i in items if i["id"] == cid))
    cr._save(items)


def inbox(c, headers):
    return c.get("/notifications/data", headers=headers).get_json()["items"]


def test_escalation_moves_ticket_to_priority_queue_with_new_sla(setup):
    c, comp, hdr, ravi, asha = setup
    assert comp["assigned_to"] == ravi["id"]
    old_due = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    edit(comp["id"], lambda x: x["sla"].update(due_at=old_due, breached=True))

    before = datetime.now(timezone.utc)
    r = escalate(c, comp["id"], hdr["sup"])
    assert r.status_code == 200
    e = r.get_json()
    assert e["escalated"] is True and e["assigned_to"] == asha["id"]
    due = datetime.fromisoformat(e["sla"]["due_at"])
    assert before + timedelta(hours=24) <= due <= datetime.now(timezone.utc) + timedelta(hours=24)
    assert e["sla"]["breached"] is False and e["sla"]["warned"] is False
    rec = e["escalations"][-1]
    assert (rec["reason"], rec["by_name"], rec["from_agent"], rec["to_agent"], rec["previous_due_at"]) == \
        ("No response from field team", "Meera", ravi["id"], asha["id"], old_due)

    data = c.get("/escalations/data", headers=hdr["sup"]).get_json()
    assert [p["id"] for p in data["priority_queue"]] == [comp["id"]]
    assert data["priority_queue"][0]["overdue"] is False and data["stalled"] == []


def test_new_sla_timer_raises_fresh_alerts(setup):
    c, comp, hdr, _, asha = setup
    edit(comp["id"], lambda x: x["sla"].update(breached=True, warned=True))
    escalate(c, comp["id"], hdr["sup"])
    items = cr._load()
    alerts = sla.check(items, now=datetime.now(timezone.utc) + timedelta(hours=23))
    assert [(a["type"], a["to"]) for a in alerts] == [("warning", asha["id"])]


def test_stakeholders_notified(setup, outbox):
    c, comp, hdr, *_ = setup
    outbox.clear()
    escalate(c, comp["id"], hdr["sup"], reason="Pipe burst again, needs senior crew")
    citizen_msg = inbox(c, hdr["citizen"])[0]
    assert citizen_msg["type"] == "escalated" and "priority" in citizen_msg["message"]
    assert "senior crew" not in citizen_msg["message"]                       # internal reason stays internal
    assert "senior crew" in inbox(c, hdr["asha"])[0]["message"]
    assert "reassigned" in inbox(c, hdr["ravi"])[0]["message"]
    assert sorted(to for _, to, *_ in outbox) == ["asha@test.com", "citizen@test.com", "ravi@test.com"]
    assert all("Complaint escalated" in m[2] for m in outbox)


def test_escalate_to_another_team(setup, make_user):
    c, comp, hdr, ravi, _ = setup
    senior = make_user("agent", email="ps@test.com", department="Public Safety Department")
    e = escalate(c, comp["id"], hdr["sup"], department="Public Safety Department").get_json()
    assert (e["department"], e["assigned_to"]) == ("Public Safety Department", senior["id"])
    assert e["escalations"][-1]["from_department"] == "Water Department"


def test_escalated_ticket_tops_receiving_agent_queue(setup):
    c, comp, hdr, _, asha = setup
    own = c.post("/submit-complaint", json=complaint_body(category="Water Supply", severity="Critical"), headers=hdr["citizen"]).get_json()
    assert own["assigned_to"] == asha["id"]
    escalate(c, comp["id"], hdr["sup"])
    q = c.get("/agent/complaints", headers=hdr["asha"]).get_json()
    assert [(i["id"], i["escalated"]) for i in q] == [(comp["id"], True), (own["id"], False)]


def test_validation(setup, make_user):
    c, comp, hdr, *_ = setup
    for reason in ("", "   ", None):
        r = escalate(c, comp["id"], hdr["sup"], reason=reason)
        assert r.status_code == 400 and "reason" in r.get_json()["error"]
    assert escalate(c, comp["id"], hdr["sup"], reason="x" * (escalation.MAX_REASON + 1)).status_code == 400
    assert escalate(c, comp["id"], hdr["sup"], department="Moon Base").status_code == 400
    r = escalate(c, comp["id"], hdr["sup"], department="Electricity Department")
    assert r.status_code == 400 and "No active agent" in r.get_json()["error"]
    assert "escalations" not in c.get(f"/complaints/{comp['id']}", headers=hdr["sup"]).get_json()


def test_only_supervisors_and_admins_escalate(setup, make_user, login):
    c, comp, hdr, *_ = setup
    assert escalate(c, comp["id"], hdr["ravi"]).status_code == 403
    assert escalate(c, comp["id"], hdr["citizen"]).status_code == 403
    assert c.get("/escalations/data", headers=hdr["ravi"]).status_code == 403
    assert escalate(c, "SCMS-20260101-99999", hdr["sup"]).status_code == 404
    make_user("admin", email="adm@test.com")
    assert escalate(c, comp["id"], login("adm@test.com")).status_code == 200
    assert c.get("/escalations").status_code == 200


def test_resolved_complaint_cannot_be_escalated(setup):
    c, comp, hdr, *_ = setup
    c.patch(f"/complaints/{comp['id']}/status", json={"status": "In Progress"}, headers=hdr["ravi"])
    c.patch(f"/complaints/{comp['id']}/status", json={"status": "Resolved", "note": "Fixed"}, headers=hdr["ravi"])
    r = escalate(c, comp["id"], hdr["sup"])
    assert r.status_code == 400 and "open" in r.get_json()["error"]


def test_stalled_complaints_listed_for_supervisor(setup):
    c, comp, hdr, *_ = setup
    unassigned = c.post("/submit-complaint", json=complaint_body(category="Electricity"), headers=hdr["citizen"]).get_json()
    fresh = c.post("/submit-complaint", json=complaint_body(category="Water Supply", severity="Low"), headers=hdr["citizen"]).get_json()
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    edit(comp["id"], lambda x: [h.update(at=three_days_ago) for h in x["history"]])

    stalled = {s["id"]: s for s in c.get("/escalations/data", headers=hdr["sup"]).get_json()["stalled"]}
    assert set(stalled) == {comp["id"], unassigned["id"]} and fresh["id"] not in stalled
    assert stalled[comp["id"]]["idle_hours"] >= escalation.STALLED_HOURS and stalled[unassigned["id"]]["unassigned"] is True

    escalate(c, comp["id"], hdr["sup"])
    assert comp["id"] not in [s["id"] for s in c.get("/escalations/data", headers=hdr["sup"]).get_json()["stalled"]]


def test_unassigned_complaint_escalated_to_team_gets_assigned(setup, make_user):
    c, _, hdr, *_ = setup
    comp = c.post("/submit-complaint", json=complaint_body(category="Electricity"), headers=hdr["citizen"]).get_json()
    assert comp["status"] == "New" and comp["needs_supervisor"] is True
    el = make_user("agent", email="el@test.com", department="Electricity Department")
    e = escalate(c, comp["id"], hdr["sup"]).get_json()
    assert (e["status"], e["assigned_to"], e["needs_supervisor"]) == ("Assigned", el["id"], False)
    assert e["history"][-1]["note"] == "Escalated to Electricity Department"
