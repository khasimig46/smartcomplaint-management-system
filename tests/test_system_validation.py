"""System validation: end-to-end flows through the HTTP API, checked against the SRS acceptance criteria.

Each test is one System Validation case (SV-xx). The docstring names the Test Plan test cases (TCxx)
and SRS requirements it validates. Unlike the module tests, these drive the whole application the way
the browser does: register / log in, then call the same endpoints the pages call.
"""
import io
import re
import statistics
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest

import routes.complaint_routes as cr
from conftest import complaint_body

pytestmark = pytest.mark.system

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2048
PDF = b"%PDF-1.4\n" + b"0" * 2048
TICKET = re.compile(r"^SCMS-\d{8}-\d{5}$")


@pytest.fixture
def world(app, make_user, login):
    """A citizen who self-registers, plus staff created the way an admin would."""
    c = app.test_client()
    assert c.post("/auth/register", json={"name": "Priya", "email": "priya@scms.in",
                                          "password": "password123"}).status_code == 201
    make_user("admin", email="admin@scms.in", name="Admin")
    adm = login("admin@scms.in")
    for body in ({"name": "Ravi", "email": "ravi@scms.in", "password": "password123", "role": "agent",
                  "department": "Water Department", "zone": "Zone 3"},
                 {"name": "Asha", "email": "asha@scms.in", "password": "password123", "role": "agent",
                  "department": "Water Department", "zone": "Zone 1"},
                 {"name": "Meera", "email": "meera@scms.in", "password": "password123", "role": "supervisor"}):
        assert c.post("/auth/users", json=body, headers=adm).status_code == 201
    hdr = {"citizen": login("priya@scms.in"), "ravi": login("ravi@scms.in"), "asha": login("asha@scms.in"),
           "sup": login("meera@scms.in"), "admin": adm}
    return c, hdr


def submit(c, headers, **overrides):
    return c.post("/submit-complaint", json=complaint_body(**overrides), headers=headers)


def move(c, cid, status, headers, note=None):
    return c.patch(f"/complaints/{cid}/status", json={"status": status, "note": note}, headers=headers)


def inbox(c, headers):
    return c.get("/notifications/data", headers=headers).get_json()["items"]


def set_due(cid, due):
    items = cr._load()
    for i in items:
        if i["id"] == cid:
            i["sla"]["due_at"] = due.isoformat()
    cr._save(items)


def test_sv01_complaint_end_to_end_happy_path(world, outbox):
    """SV-01 -> TC01, TC07, TC08, TC10, TC13; FR-001, FR-003, FR-004, FR-005, FR-007, FR-013.

    Citizen submits with an image and GPS, the complaint is routed to the zone agent, worked through
    every lifecycle state, resolved with notes, and closed by the citizen.
    """
    c, hdr = world
    form = {"title": "Pothole on MG Road water main", "description": "Water leaking from main pipe on 5th cross",
            "severity": "High", "category": "Water Supply", "latitude": "12.9716", "longitude": "77.5946",
            "zone": "Zone 3", "images": (io.BytesIO(PNG), "pothole.png")}
    r = c.post("/submit-complaint", data=form, headers=hdr["citizen"], content_type="multipart/form-data")
    assert r.status_code == 201
    comp = r.get_json()
    cid = comp["id"]
    assert TICKET.match(cid)
    assert comp["location"] == {"latitude": 12.9716, "longitude": 77.5946} and len(comp["images"]) == 1
    assert comp["department"] == "Water Department" and comp["status"] == "Assigned"
    ravi = c.get("/auth/me", headers=hdr["ravi"]).get_json()
    assert comp["assigned_to"] == ravi["id"], "zone-matching agent should be chosen"
    assert comp["sla"]["hours"] == 24

    assert [q["id"] for q in c.get("/agent/complaints", headers=hdr["ravi"]).get_json()] == [cid]
    assert move(c, cid, "In Progress", hdr["ravi"]).status_code == 200
    assert move(c, cid, "Pending Info", hdr["ravi"], "Which side of the road?").status_code == 200
    assert move(c, cid, "In Progress", hdr["ravi"]).status_code == 200
    assert move(c, cid, "Resolved", hdr["ravi"], "Pipe joint replaced").status_code == 200
    assert move(c, cid, "Closed", hdr["citizen"]).status_code == 200

    final = c.get(f"/complaints/{cid}", headers=hdr["citizen"]).get_json()
    states = [h["status"] for h in final["history"]]
    assert states == ["New", "Assigned", "In Progress", "Pending Info", "In Progress", "Resolved", "Closed"]
    stamps = [datetime.fromisoformat(h["at"]) for h in final["history"]]
    assert stamps == sorted(stamps) and all(h["by"] for h in final["history"])
    assert final["resolution"]["notes"] == "Pipe joint replaced"

    kinds = [n["type"] for n in inbox(c, hdr["citizen"])]
    assert {"submitted", "status_update", "resolution"} <= set(kinds)
    assert any("Which side of the road?" in n["message"] for n in inbox(c, hdr["citizen"]))
    assert ("email", "priya@scms.in") in {(k, to) for k, to, *_ in outbox}


def test_sv02_submission_validation_and_limits(world):
    """SV-02 -> TC02, TC03, TC04; FR-001 (mandatory fields, 120 / 2000 char limits, 5 MB image limit)."""
    c, hdr = world
    r = c.post("/submit-complaint", json={"title": "", "description": "", "severity": ""}, headers=hdr["citizen"])
    assert r.status_code == 400 and {"title", "description", "severity"} <= set(r.get_json()["fields"])

    assert submit(c, hdr["citizen"], title="T" * 120, description="D" * 2000).status_code == 201
    assert "title" in submit(c, hdr["citizen"], title="T" * 121).get_json()["fields"]
    assert "description" in submit(c, hdr["citizen"], description="D" * 2001).get_json()["fields"]

    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024)
    r = c.post("/submit-complaint", data={**complaint_body(), "images": (io.BytesIO(big), "large.png")},
               headers=hdr["citizen"], content_type="multipart/form-data")
    assert r.status_code == 400 and "5 MB" in r.get_json()["fields"]["images"]
    assert len(c.get("/complaints/mine", headers=hdr["citizen"]).get_json()) == 1, "rejected submissions are not stored"


def test_sv03_nlp_suggestions_and_override(world):
    """SV-03 -> TC05, TC06 (manual-choice fallback); FR-002."""
    c, hdr = world
    s = c.post("/suggest-category", json={"text": "water leakage from main pipe on 5th cross"}).get_json()
    assert len(s) == 3 and s[0]["category"] == "Water Supply"
    assert [x["confidence"] for x in s] == sorted((x["confidence"] for x in s), reverse=True)

    comp = submit(c, hdr["citizen"], category="Roads").get_json()   # citizen overrides the suggestion
    assert comp["category"] == "Roads" and comp["overridden"] is True
    r = c.post("/override-category", json={"complaint_id": comp["id"], "category": "Water Supply"}, headers=hdr["citizen"])
    assert r.status_code == 200 and r.get_json()["department"] == "Water Department"


def test_sv04_unassignable_complaint_goes_to_supervisor_then_escalated(world):
    """SV-04 -> TC09, TC16; FR-004 (no agent), FR-009 (escalation, SLA reset, priority queue)."""
    c, hdr = world
    comp = submit(c, hdr["citizen"], category="Electricity").get_json()   # no Electricity agent exists
    assert comp["assigned_to"] is None and comp["needs_supervisor"] is True and comp["status"] == "New"
    assert any(n["type"] == "needs_supervisor" for n in inbox(c, hdr["sup"]))

    old_due = comp["sla"]["due_at"]
    time.sleep(0.01)
    r = c.post(f"/complaints/{comp['id']}/escalate", json={"reason": "No response", "department": "Water Department"},
               headers=hdr["sup"])
    assert r.status_code == 200
    esc = r.get_json()
    assert esc["escalated"] and esc["status"] == "Assigned" and esc["sla"]["due_at"] > old_due
    queue = c.get("/escalations/data", headers=hdr["sup"]).get_json()["priority_queue"]
    assert comp["id"] in [q["id"] for q in queue]
    assert any(n["type"] == "escalated" for n in inbox(c, hdr["citizen"]))


def test_sv05_sla_warning_and_breach_alerts(world):
    """SV-05 -> TC11, TC12; FR-006 (warning < 2 h, breach), FR-011 (overdue on dashboard)."""
    c, hdr = world
    cid = submit(c, hdr["citizen"], category="Water Supply", zone="Zone 3").get_json()["id"]
    now = datetime.now(timezone.utc)

    set_due(cid, now + timedelta(minutes=90))
    assert [a["type"] for a in c.post("/sla/check", headers=hdr["sup"]).get_json()["new_alerts"]] == ["warning"]
    assert any(n["type"] == "sla_warning" for n in inbox(c, hdr["ravi"]))

    set_due(cid, now - timedelta(minutes=5))
    assert [a["type"] for a in c.post("/sla/check", headers=hdr["sup"]).get_json()["new_alerts"]] == ["breach"]
    assert any(n["type"] == "sla_breach" for n in inbox(c, hdr["sup"]))
    assert c.post("/sla/check", headers=hdr["sup"]).get_json()["new_alerts"] == [], "each alert fires once"
    assert c.get("/dashboard/data", headers=hdr["sup"]).get_json()["overdue"] == 1


@pytest.mark.parametrize("method,path,allowed", [
    ("post", "/submit-complaint", {"citizen"}),
    ("get", "/complaints", {"ravi", "sup", "admin"}),
    ("get", "/complaints/mine", {"citizen"}),
    ("get", "/agent/complaints", {"ravi"}),
    ("get", "/dashboard/data", {"sup", "admin"}),
    ("get", "/escalations/data", {"sup", "admin"}),
    ("put", "/sla/rules", {"admin"}),
    ("get", "/auth/users", {"admin"}),
    ("post", "/auth/users", {"admin"}),
])
def test_sv06_rbac_matrix(world, method, path, allowed):
    """SV-06 -> TC17; FR-010 (permissions enforced per role on every API call)."""
    c, hdr = world
    def body(who):
        return {"/submit-complaint": complaint_body(), "/sla/rules": {"High": 24},
                "/auth/users": {"name": "X", "email": f"x-{who}@scms.in", "password": "password123",
                                "role": "agent", "department": "Water Department"}}.get(path)

    for who in ("citizen", "ravi", "sup", "admin"):
        r = getattr(c, method)(path, json=body(who), headers=hdr[who])
        if who in allowed:
            assert r.status_code < 400, f"{who} should be allowed {method.upper()} {path}"
        else:
            assert r.status_code == 403, f"{who} must be denied {method.upper()} {path}"
    assert getattr(c, method)(path, json=body("anon")).status_code == 401, "no token -> 401"


def test_sv07_authentication_security(world, app):
    """SV-07 -> Test Plan 5.1 security validation; FR-010, NFR-002 (application-level controls)."""
    c, hdr = world
    assert c.post("/auth/login", json={"email": "priya@scms.in", "password": "wrong"}).status_code == 401
    forged = jwt.encode({"sub": "anything", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "not-the-key",
                        algorithm="HS256")
    assert c.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    expired = jwt.encode({"sub": "x", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
                         app.config["SECRET_KEY"], algorithm="HS256")
    assert c.get("/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    r = c.post("/auth/register", json={"name": "Eve", "email": "eve@scms.in", "password": "password123", "role": "admin"})
    assert r.status_code == 201 and r.get_json()["role"] == "citizen", "self-registration cannot pick a role"
    assert "password" not in r.get_json() and "password_hash" not in r.get_json()

    other = c.post("/auth/register", json={"name": "Om", "email": "om@scms.in", "password": "password123"})
    assert other.status_code == 201
    om = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "om@scms.in", "password": "password123"})
          .get_json()["token"]}
    cid = submit(c, hdr["citizen"]).get_json()["id"]
    assert c.get(f"/complaints/{cid}", headers=om).status_code == 403, "citizens cannot read others' complaints"
    exe = b"MZ\x90\x00" + b"\x00" * 100
    r = c.post("/submit-complaint", data={**complaint_body(), "images": (io.BytesIO(exe), "photo.png")},
               headers=hdr["citizen"], content_type="multipart/form-data")
    assert r.status_code == 400, "file type is checked by content, not by extension"


def test_sv08_notes_and_evidence(world):
    """SV-08 -> TC21, TC22; FR-013 (notes required to resolve), FR-014 (notes, evidence <= 10 MB, staff-only)."""
    c, hdr = world
    cid = submit(c, hdr["citizen"], category="Water Supply", zone="Zone 3").get_json()["id"]
    assert c.post(f"/complaints/{cid}/notes", json={"text": "Valve checked"}, headers=hdr["ravi"]).status_code == 201
    notes = c.get(f"/complaints/{cid}/notes", headers=hdr["ravi"]).get_json()
    assert notes[0]["by_name"] == "Ravi" and notes[0]["at"]
    assert "notes" not in c.get(f"/complaints/{cid}", headers=hdr["citizen"]).get_json()

    ok = c.post(f"/complaints/{cid}/evidence", data={"files": [(io.BytesIO(PNG), "after.png"), (io.BytesIO(PDF), "report.pdf")]},
                headers=hdr["ravi"], content_type="multipart/form-data")
    assert ok.status_code in (200, 201)
    big = b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024)
    r = c.post(f"/complaints/{cid}/evidence", data={"files": (io.BytesIO(big), "big.pdf")},
               headers=hdr["ravi"], content_type="multipart/form-data")
    assert r.status_code == 400
    r = c.post(f"/complaints/{cid}/evidence", data={"files": (io.BytesIO(PNG), "x.png")},
               headers=hdr["asha"], content_type="multipart/form-data")
    assert r.status_code == 403, "only the assigned agent or a supervisor may upload"

    assert move(c, cid, "In Progress", hdr["ravi"]).status_code == 200
    assert move(c, cid, "Resolved", hdr["ravi"]).status_code == 400, "resolution notes are required"
    assert move(c, cid, "Resolved", hdr["ravi"], "Fixed").status_code == 200
    assert move(c, cid, "In Progress", hdr["citizen"]).status_code == 200, "citizen may reopen (TC23)"


def test_sv09_dashboard_reflects_stored_data(world):
    """SV-09 -> TC18, TC24; FR-011 (counts, SLA compliance, CSV report, 60 s refresh)."""
    c, hdr = world
    a = submit(c, hdr["citizen"], category="Water Supply", zone="Zone 3").get_json()["id"]
    submit(c, hdr["citizen"], category="Water Supply", zone="Zone 3")
    move(c, a, "In Progress", hdr["ravi"])
    move(c, a, "Resolved", hdr["ravi"], "Done")
    k = c.get("/dashboard/data", headers=hdr["sup"]).get_json()
    assert (k["total"], k["open"], k["resolved"], k["sla_compliance_percent"]) == (2, 1, 1, 100.0)
    csv = c.get("/dashboard/report.csv", headers=hdr["sup"])
    assert csv.status_code == 200 and csv.data.decode().count("\n") >= 3
    assert b"60" in c.get("/dashboard").data


def test_sv10_response_time_smoke(world):
    """SV-10 -> TC20 (partial). Single-client, in-process latency of the main API calls.

    This is NOT the 500-concurrent-user load test NFR-001 asks for; it only shows the application code
    itself stays well inside the 500 ms p99 budget, so the load test has headroom to measure.
    """
    c, hdr = world
    cid = submit(c, hdr["citizen"], category="Water Supply", zone="Zone 3").get_json()["id"]
    calls = [lambda: c.get(f"/complaints/{cid}", headers=hdr["citizen"]),
             lambda: c.get("/agent/complaints", headers=hdr["ravi"]),
             lambda: c.get("/dashboard/data", headers=hdr["sup"]),
             lambda: c.get("/notifications/data", headers=hdr["citizen"])]
    samples = []
    for _ in range(50):
        for call in calls:
            t = time.perf_counter()
            assert call().status_code == 200
            samples.append((time.perf_counter() - t) * 1000)
    p99 = statistics.quantiles(samples, n=100)[98]
    print(f"\nSV-10 latency over {len(samples)} requests: median {statistics.median(samples):.1f} ms, p99 {p99:.1f} ms")
    assert p99 < 500
