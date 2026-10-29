from services.routing import department_for, route


def agent(aid, dept, zone=None, created="2026-10-01", active=True):
    return {"id": aid, "role": "agent", "department": dept, "zone": zone, "active": active, "created_at": created}


def test_correct_department_for_each_category():
    assert department_for("Water Supply") == "Water Department"
    assert department_for("Electricity") == "Electricity Department"
    assert department_for("Something new") == "General Administration"


def test_agent_assignment_is_automatic():
    r = route("Water Supply", [agent("A1", "Water Department")], [])
    assert r == {"department": "Water Department", "assigned_to": "A1", "needs_supervisor": False}


def test_only_agents_from_the_right_department():
    users = [agent("E1", "Electricity Department"), agent("W1", "Water Department")]
    assert route("Water Supply", users, [])["assigned_to"] == "W1"


def test_workload_balancing_picks_least_loaded():
    users = [agent("A1", "Water Department", created="2026-10-01"), agent("A2", "Water Department", created="2026-10-02")]
    complaints = [{"assigned_to": "A1", "status": "Assigned"}, {"assigned_to": "A1", "status": "In Progress"},
                  {"assigned_to": "A2", "status": "Assigned"}]
    assert route("Water Supply", users, complaints)["assigned_to"] == "A2"


def test_resolved_complaints_do_not_count_as_load():
    users = [agent("A1", "Water Department", created="2026-10-01"), agent("A2", "Water Department", created="2026-10-02")]
    complaints = [{"assigned_to": "A1", "status": "Resolved"}, {"assigned_to": "A2", "status": "Assigned"}]
    assert route("Water Supply", users, complaints)["assigned_to"] == "A1"


def test_same_zone_agent_preferred():
    users = [agent("A1", "Water Department", zone="Zone 1"), agent("A3", "Water Department", zone="Zone 3")]
    assert route("Water Supply", users, [], zone="Zone 3")["assigned_to"] == "A3"


def test_unavailable_agents_go_to_supervisor_queue():
    users = [agent("A1", "Water Department", active=False), agent("E1", "Electricity Department")]
    r = route("Water Supply", users, [])
    assert r["assigned_to"] is None and r["needs_supervisor"] is True


def test_submitted_complaint_is_routed(app, make_user, citizen):
    a = make_user("agent", department="Electricity Department")
    body = {"title": "Street light", "description": "Street light not working, power cut", "severity": "Medium"}
    c = app.test_client().post("/submit-complaint", json=body, headers=citizen).get_json()
    assert c["department"] == "Electricity Department"
    assert c["assigned_to"] == a["id"]
