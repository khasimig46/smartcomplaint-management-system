"""Sprint 3 Task 1: concurrency-safe storage and unique ticket IDs.

Each test is one test case from Documents/Sprint_3_Test_Cases.md (SRS section 3 template). Test data is taken
from the SRS test cases (UT-01, IT-02, ST-03) and expected results from the SRS acceptance criteria.
"""
import json
import re
import threading
from datetime import datetime, timezone

import pytest

import routes.complaint_routes as cr
import services.auth as auth
from services import storage

SIMULTANEOUS = 20

# SRS UT-01 test data
POTHOLE = {"title": "Pothole on MG Road", "description": "Road surface damaged", "category": "Roads",
           "severity": "High", "latitude": "12.9716", "longitude": "77.5946"}


def run_together(fn, n=SIMULTANEOUS):
    """Start n requests at the same moment and wait for all of them."""
    start = threading.Barrier(n)
    results = [None] * n

    def worker(i):
        start.wait()
        results[i] = fn(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def submit(app, headers):
    r = app.test_client().post("/submit-complaint", json=POTHOLE, headers=headers)
    return r.status_code, r.get_json()


@pytest.fixture
def admin(make_user, login):
    make_user("admin", email="admin@scms.in", name="Administrator")
    return login("admin@scms.in")


@pytest.fixture
def ravi(app, make_user, login, citizen):
    """SRS IT-02: Agent Ravi, Water Dept - Zone 3, with a Water Supply complaint from Zone 3 assigned to him."""
    make_user("agent", email="ravi@scms.in", name="Ravi", department="Water Department", zone="Zone 3")
    body = {**POTHOLE, "title": "Water leakage", "description": "Water leakage from main pipe on 5th cross",
            "category": "Water Supply", "zone": "Zone 3"}
    comp = app.test_client().post("/submit-complaint", json=body, headers=citizen).get_json()
    assert comp["assigned_to"] and comp["status"] == "Assigned"
    return comp, login("ravi@scms.in")


def test_UT04_simultaneous_submissions_get_unique_ticket_ids(app, citizen):
    """UT-04 Ticket ID Generation (FR-003). Pass: unique ID shown on confirmation. Fail: duplicate ID or missing."""
    results = run_together(lambda _: submit(app, citizen))
    assert [code for code, _ in results] == [201] * SIMULTANEOUS
    ids = [body.get("id") for _, body in results]
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert all(re.fullmatch(rf"SCMS-{today}-\d{{5}}", i or "") for i in ids)       # SCMS-YYYYMMDD-NNNNN, none missing
    assert len(set(ids)) == SIMULTANEOUS                                             # no duplicate ID


def test_UT05_simultaneous_submissions_are_all_saved_with_all_fields(app, citizen):
    """UT-05 Complaint Submission (FR-001). Pass: complaint saved with all fields."""
    ids = [body["id"] for _, body in run_together(lambda _: submit(app, citizen))]
    saved = {c["id"]: c for c in cr._load()}
    assert sorted(saved) == sorted(ids)
    for cid in ids:
        c = app.test_client().get(f"/complaints/{cid}", headers=citizen).get_json()
        assert (c["title"], c["description"], c["category"], c["severity"]) == \
               ("Pothole on MG Road", "Road surface damaged", "Roads", "High")
        assert c["location"] == {"latitude": 12.9716, "longitude": 77.5946}


def test_UT06_simultaneous_account_creation_keeps_every_account(app, admin, login):
    """UT-06 User Management (FR-010, UC-09). Pass: every account created with the correct role; each can log in."""
    def create(i):
        body = {"name": f"Agent {i}", "email": f"agent{i}@scms.in", "password": "password123",
                "role": "agent", "department": "Roads & Infrastructure"}
        return app.test_client().post("/auth/users", json=body, headers=admin).status_code

    assert run_together(create) == [201] * SIMULTANEOUS
    agents = [u for u in auth.load_users() if u["role"] == "agent"]
    assert sorted(u["email"] for u in agents) == sorted(f"agent{i}@scms.in" for i in range(SIMULTANEOUS))
    me = app.test_client().get("/auth/me", headers=login("agent7@scms.in")).get_json()
    assert me["role"] == "agent"


def test_UT07_simultaneous_duplicate_email_creates_one_account(app, admin):
    """UT-07 User Management (UC-09 alternative flow 3a). Pass: one account; the rest get a duplicate-account error."""
    priya = {"name": "Priya S", "email": "priya@scms.in", "password": "password123",      # SRS ST-03 test data
             "role": "agent", "department": "Roads & Infrastructure"}
    responses = run_together(lambda _: app.test_client().post("/auth/users", json=priya, headers=admin), n=8)
    assert sorted(r.status_code for r in responses) == [201] + [409] * 7
    assert all("already exists" in r.get_json()["error"] for r in responses if r.status_code == 409)
    assert [u["email"] for u in auth.load_users()].count("priya@scms.in") == 1


def test_UT08_simultaneous_notes_saved_with_agent_name_and_timestamp(app, ravi):
    """UT-08 Add Notes and Evidence (FR-014, US-06). Pass: note saved with agent name and timestamp."""
    comp, hdr = ravi
    codes = run_together(lambda i: app.test_client().post(
        f"/complaints/{comp['id']}/notes", json={"text": f"Field visit update {i}"}, headers=hdr).status_code)
    assert codes == [201] * SIMULTANEOUS
    notes = app.test_client().get(f"/complaints/{comp['id']}/notes", headers=hdr).get_json()
    assert sorted(n["text"] for n in notes) == sorted(f"Field visit update {i}" for i in range(SIMULTANEOUS))
    assert all(n["by_name"] == "Ravi" and datetime.fromisoformat(n["at"]) for n in notes)
    assert len({n["id"] for n in notes}) == SIMULTANEOUS


def test_IT04_status_change_and_notes_at_the_same_time_are_all_logged(app, ravi, citizen):
    """IT-04 Complaint Lifecycle + Notes (FR-005, FR-014). Pass: status history shows all transitions with
    timestamps. Fail: transition skipped or unlogged."""
    comp, hdr = ravi

    def act(i):
        c = app.test_client()
        if i == 0:
            return c.patch(f"/complaints/{comp['id']}/status", json={"status": "In Progress"}, headers=hdr).status_code
        return c.post(f"/complaints/{comp['id']}/notes", json={"text": f"Checked valve {i}"}, headers=hdr).status_code

    assert sorted(run_together(act, n=10)) == [200] + [201] * 9
    c = app.test_client().get(f"/complaints/{comp['id']}", headers=citizen).get_json()
    assert c["status"] == "In Progress"
    assert [h["status"] for h in c["history"]] == ["New", "Assigned", "In Progress"]
    assert all(datetime.fromisoformat(h["at"]) for h in c["history"])
    notes = app.test_client().get(f"/complaints/{comp['id']}/notes", headers=hdr).get_json()
    assert len(notes) == 9


def test_UT09_failed_save_does_not_corrupt_saved_complaints(app, citizen, monkeypatch):
    """UT-09 Data Reliability (NFR-003, RPO). Pass: a failure while saving loses no previously saved complaint."""
    first = submit(app, citizen)[1]

    def disk_full(data, f, **kw):
        f.write(json.dumps(data)[:20])          # part of the file is written, then the disk fills up
        raise OSError("No space left on device")

    with monkeypatch.context() as m:
        m.setattr(storage.json, "dump", disk_full)
        with pytest.raises(OSError):
            submit(app, citizen)

    r = app.test_client().get(f"/complaints/{first['id']}", headers=citizen)
    assert r.status_code == 200 and r.get_json()["title"] == "Pothole on MG Road"
    assert [c["id"] for c in cr._load()] == [first["id"]]                 # failed submission not half-saved
    assert not list(cr.STORE.parent.glob(f".{cr.STORE.name}.*.tmp"))      # no temp file left behind
