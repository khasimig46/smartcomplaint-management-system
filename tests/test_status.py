import pytest

from conftest import complaint_body
from services.status import TransitionError, change


@pytest.fixture
def setup(app, make_user, login, citizen):
    agent = make_user("agent", email="ag@test.com", department="Water Department")
    make_user("supervisor", email="sup@test.com")
    c = app.test_client()
    comp = c.post("/submit-complaint", json=complaint_body(category="Water Supply"), headers=citizen).get_json()
    return c, comp, {"citizen": citizen, "agent": login("ag@test.com"), "sup": login("sup@test.com")}, agent


def move(c, cid, status, headers, note=None):
    return c.patch(f"/complaints/{cid}/status", json={"status": status, "note": note}, headers=headers)


def test_new_complaint_starts_new_then_assigned(setup):
    _, comp, _, agent = setup
    assert comp["status"] == "Assigned"
    assert [h["status"] for h in comp["history"]] == ["New", "Assigned"]
    assert all(h["at"] for h in comp["history"])


def test_status_changes_recorded_with_timestamps(setup):
    c, comp, hdr, _ = setup
    for s in ("In Progress", "Pending Info", "In Progress", "Resolved"):
        r = move(c, comp["id"], s, hdr["agent"], note=f"to {s}")
        assert r.status_code == 200
    r = move(c, comp["id"], "Closed", hdr["citizen"])
    assert r.get_json()["status"] == "Closed"


def test_timeline_shows_complete_history(setup):
    c, comp, hdr, _ = setup
    move(c, comp["id"], "In Progress", hdr["agent"])
    move(c, comp["id"], "Resolved", hdr["agent"], note="Pipe replaced")
    hist = c.get(f"/complaints/{comp['id']}", headers=hdr["citizen"]).get_json()["history"]
    assert [h["status"] for h in hist] == ["New", "Assigned", "In Progress", "Resolved"]
    assert hist[-1]["note"] == "Pipe replaced"


def test_invalid_transition_rejected(setup):
    c, comp, hdr, _ = setup
    r = move(c, comp["id"], "Closed", hdr["sup"])
    assert r.status_code == 400 and "Cannot move" in r.get_json()["error"]
    with pytest.raises(TransitionError):
        change({"status": "New"}, "Resolved", "x")


def test_permissions_on_status_changes(setup, make_user, login):
    c, comp, hdr, _ = setup
    make_user("agent", email="other@test.com", department="Water Department")
    assert move(c, comp["id"], "In Progress", login("other@test.com")).status_code == 403   # not their complaint
    assert move(c, comp["id"], "In Progress", hdr["citizen"]).status_code == 403            # citizen cannot start work
    assert move(c, comp["id"], "In Progress", hdr["agent"]).status_code == 200


def test_only_involved_users_can_view(setup, make_user, login):
    c, comp, hdr, _ = setup
    make_user(email="stranger@test.com")
    assert c.get(f"/complaints/{comp['id']}", headers=login("stranger@test.com")).status_code == 403
    assert c.get(f"/complaints/{comp['id']}", headers=hdr["sup"]).status_code == 200


def test_unassigned_complaint_stays_new(app, citizen):
    comp = app.test_client().post("/submit-complaint", json=complaint_body(), headers=citizen).get_json()
    assert comp["status"] == "New" and comp["needs_supervisor"] is True
