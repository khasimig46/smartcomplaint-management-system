from datetime import datetime, timedelta, timezone

import pytest

import routes.complaint_routes as cr
from conftest import complaint_body
from services import notifications


@pytest.fixture
def setup(app, make_user, login, citizen):
    agent = make_user("agent", email="ag@test.com", department="Water Department")
    make_user("supervisor", email="sup@test.com")
    c = app.test_client()
    comp = c.post("/submit-complaint", json=complaint_body(category="Water Supply"), headers=citizen).get_json()
    return c, comp, {"citizen": citizen, "agent": login("ag@test.com"), "sup": login("sup@test.com")}, agent


def inbox(c, headers):
    return c.get("/notifications/data", headers=headers).get_json()


def move(c, cid, status, headers, note=None):
    return c.patch(f"/complaints/{cid}/status", json={"status": status, "note": note}, headers=headers)


def test_submission_notifies_citizen_and_assigned_agent(setup, outbox):
    c, comp, hdr, _ = setup
    mine = inbox(c, hdr["citizen"])
    assert mine["unread"] == 1 and mine["items"][0]["type"] == "submitted" and comp["id"] in mine["items"][0]["message"]
    assert inbox(c, hdr["agent"])["items"][0]["type"] == "assigned"
    assert {(kind, to) for kind, to, *_ in outbox} == {("email", "citizen@test.com"), ("email", "ag@test.com")}


def test_status_updates_sent_to_citizen(setup, outbox):
    c, comp, hdr, _ = setup
    outbox.clear()
    assert move(c, comp["id"], "In Progress", hdr["agent"]).status_code == 200
    latest = inbox(c, hdr["citizen"])["items"][0]
    assert latest["type"] == "status_update" and "In Progress" in latest["message"]
    assert latest["delivery"] == {"in_app": "delivered", "email": "sent"}
    assert [to for _, to, *_ in outbox] == ["citizen@test.com"]          # the agent made the change
    assert "Status: In Progress" in outbox[0][3]                          # email has the complaint summary


def test_resolution_notification_sent(setup):
    c, comp, hdr, _ = setup
    move(c, comp["id"], "In Progress", hdr["agent"])
    move(c, comp["id"], "Resolved", hdr["agent"], note="Pipe replaced")
    latest = inbox(c, hdr["citizen"])["items"][0]
    assert latest["type"] == "resolution" and "Pipe replaced" in latest["message"]
    move(c, comp["id"], "Closed", hdr["citizen"])
    assert "Closed" in inbox(c, hdr["agent"])["items"][0]["message"]   # agent hears the citizen closed it


def test_sms_only_for_opted_in_users(setup, outbox):
    c, comp, hdr, _ = setup
    move(c, comp["id"], "In Progress", hdr["agent"])
    assert not [m for m in outbox if m[0] == "sms"]
    assert c.put("/notifications/preferences", json={"sms": True}, headers=hdr["citizen"]).status_code == 400   # no phone
    r = c.put("/notifications/preferences", json={"sms": True, "phone": "+91 98765 43210"}, headers=hdr["citizen"])
    assert r.get_json() == {"email": True, "sms": True, "phone": "+919876543210"}
    move(c, comp["id"], "Pending Info", hdr["agent"])
    assert [m[1] for m in outbox if m[0] == "sms"] == ["+919876543210"]


def test_email_opt_out_and_preference_validation(setup, outbox):
    c, comp, hdr, _ = setup
    assert c.put("/notifications/preferences", json={"email": False}, headers=hdr["citizen"]).get_json()["email"] is False
    outbox.clear()
    move(c, comp["id"], "In Progress", hdr["agent"])
    assert outbox == [] and inbox(c, hdr["citizen"])["items"][0]["delivery"] == {"in_app": "delivered"}
    assert c.put("/notifications/preferences", json={"phone": "12345"}, headers=hdr["citizen"]).status_code == 400
    assert c.put("/notifications/preferences", json={"email": "yes"}, headers=hdr["citizen"]).status_code == 400
    assert c.get("/notifications/preferences", headers=hdr["citizen"]).get_json()["email"] is False


def test_sla_warning_and_breach_notifications(setup):
    c, comp, hdr, _ = setup
    items = cr._load(); items[0]["sla"]["due_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(); cr._save(items)
    c.post("/sla/check", headers=hdr["sup"])
    assert inbox(c, hdr["agent"])["items"][0]["type"] == "sla_warning"
    items = cr._load(); items[0]["sla"]["due_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(); cr._save(items)
    c.post("/sla/check", headers=hdr["sup"])
    assert inbox(c, hdr["sup"])["items"][0]["type"] == "sla_breach"


def test_unassigned_complaint_notifies_supervisors(app, make_user, login, citizen):
    make_user("supervisor", email="sup@test.com")
    c = app.test_client()
    c.post("/submit-complaint", json=complaint_body(), headers=citizen)
    assert inbox(c, login("sup@test.com"))["items"][0]["type"] == "needs_supervisor"


def test_reassigned_agent_notified_on_override(setup, make_user, login):
    c, comp, hdr, _ = setup
    make_user("agent", email="el@test.com", department="Electricity Department")
    c.post("/override-category", json={"complaint_id": comp["id"], "category": "Electricity"}, headers=hdr["sup"])
    assert inbox(c, login("el@test.com"))["items"][0]["type"] == "assigned"


def test_mark_read_and_privacy(setup):
    c, comp, hdr, _ = setup
    move(c, comp["id"], "In Progress", hdr["agent"])
    items = inbox(c, hdr["citizen"])["items"]
    assert len(items) == 2 and inbox(c, hdr["citizen"])["unread"] == 2
    assert c.post(f"/notifications/{items[0]['id']}/read", headers=hdr["agent"]).status_code == 404   # not theirs
    assert c.post(f"/notifications/{items[0]['id']}/read", headers=hdr["citizen"]).status_code == 200
    assert inbox(c, hdr["citizen"])["unread"] == 1
    assert len(c.get("/notifications/data?unread=1", headers=hdr["citizen"]).get_json()["items"]) == 1
    assert c.post("/notifications/read-all", headers=hdr["citizen"]).get_json() == {"read": 1}
    assert c.get("/notifications/data").status_code == 401
    assert c.get("/notifications").status_code == 200


def test_provider_failure_does_not_break_request(setup, monkeypatch):
    c, comp, hdr, _ = setup
    def down(*_):
        raise OSError("SMTP server unreachable")
    monkeypatch.setattr(notifications, "send_email", down)
    assert move(c, comp["id"], "In Progress", hdr["agent"]).status_code == 200
    assert inbox(c, hdr["citizen"])["items"][0]["delivery"] == {"in_app": "delivered", "email": "failed"}


def test_email_provider(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert notifications.send_email("a@test.com", "Hi", "Body") == "logged"
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.host, self.port = host, port
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def starttls(self):
            pass
        def login(self, user, password):
            pass
        def send_message(self, msg):
            sent.append((self.host, self.port, msg["To"], msg["Subject"]))

    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("SMTP_HOST", "smtp.test.com"); monkeypatch.setenv("SMTP_PORT", "2525")
    assert notifications.send_email("a@test.com", "Hi", "Body") == "sent"
    assert sent == [("smtp.test.com", 2525, "a@test.com", "Hi")]


def test_sms_provider(monkeypatch):
    for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"):
        monkeypatch.delenv(k, raising=False)
    assert notifications.send_sms("+919876543210", "Hi") == "logged"
    calls = []

    class Resp:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return b"{}"

    monkeypatch.setattr(notifications.urlrequest, "urlopen", lambda req, timeout: calls.append(req) or Resp())
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123"); monkeypatch.setenv("TWILIO_AUTH_TOKEN", "t"); monkeypatch.setenv("TWILIO_FROM", "+15550001111")
    assert notifications.send_sms("+919876543210", "Hi") == "sent"
    assert calls[0].full_url.endswith("/Accounts/AC123/Messages.json") and b"To=%2B919876543210" in calls[0].data
