"""Sprint 3 Task 7 (issue #32): citizen reply to "Pending Info". FR-013, UC-04 alternative flow 3a."""
import pytest

from conftest import complaint_body


@pytest.fixture
def setup(app, make_user, login, citizen):
    make_user("agent", email="ag@test.com", name="Ravi", department="Water Department")
    make_user("citizen", email="other@test.com")
    c = app.test_client()
    comp = c.post("/submit-complaint", json=complaint_body(category="Water Supply"), headers=citizen).get_json()
    hdr = {"citizen": citizen, "agent": login("ag@test.com"), "other": login("other@test.com")}
    return c, comp["id"], hdr


def move(c, cid, status, headers, note=None):
    return c.patch(f"/complaints/{cid}/status", json={"status": status, "note": note}, headers=headers)


def ask(c, cid, hdr, question="Which house number is it?"):
    move(c, cid, "In Progress", hdr["agent"])
    assert move(c, cid, "Pending Info", hdr["agent"], note=question).status_code == 200


def reply(c, cid, headers, text):
    return c.post(f"/complaints/{cid}/reply", json={"text": text}, headers=headers)


def test_reply_is_logged_and_work_resumes(setup):
    c, cid, hdr = setup
    ask(c, cid, hdr)
    r = reply(c, cid, hdr["citizen"], "  House 42, near the temple  ")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "In Progress"
    assert body["replies"][-1]["text"] == "House 42, near the temple"
    last = body["history"][-1]
    assert last["status"] == "In Progress" and last["by"] == body["citizen_id"]
    assert last["note"] == "Citizen replied: House 42, near the temple"


def test_agent_is_notified_with_the_reply(setup):
    c, cid, hdr = setup
    ask(c, cid, hdr)
    reply(c, cid, hdr["citizen"], "House 42")
    latest = c.get("/notifications/data", headers=hdr["agent"]).get_json()["items"][0]
    assert latest["type"] == "citizen_reply" and "House 42" in latest["message"]


def test_only_the_owner_can_reply(setup):
    c, cid, hdr = setup
    ask(c, cid, hdr)
    assert reply(c, cid, hdr["other"], "Not my complaint").status_code == 403
    assert reply(c, cid, hdr["agent"], "Staff cannot use this").status_code == 403
    assert reply(c, "SCMS-00000000-00000", hdr["citizen"], "x").status_code == 404


def test_reply_only_while_pending_info(setup):
    c, cid, hdr = setup
    move(c, cid, "In Progress", hdr["agent"])
    r = reply(c, cid, hdr["citizen"], "Unprompted reply")
    assert r.status_code == 400 and "Pending Info" in r.get_json()["error"]


@pytest.mark.parametrize("bad", ["", "   ", None, 42, "x" * 2001])
def test_reply_text_is_validated(setup, bad):
    c, cid, hdr = setup
    ask(c, cid, hdr)
    assert reply(c, cid, hdr["citizen"], bad).status_code == 400
    assert c.get(f"/complaints/{cid}", headers=hdr["citizen"]).get_json()["status"] == "Pending Info"


def test_second_query_and_reply_round_trip(setup):
    c, cid, hdr = setup
    ask(c, cid, hdr, "Which street?")
    reply(c, cid, hdr["citizen"], "5th Cross")
    assert move(c, cid, "Pending Info", hdr["agent"], note="Which house?").status_code == 200
    body = reply(c, cid, hdr["citizen"], "House 42").get_json()
    assert [r["text"] for r in body["replies"]] == ["5th Cross", "House 42"] and body["status"] == "In Progress"
