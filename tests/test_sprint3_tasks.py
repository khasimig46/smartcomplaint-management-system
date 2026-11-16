import threading
import time

import routes.complaint_routes as cr
from conftest import complaint_body
from services import auth, notifications


def test_admin_user_crud_revokes_old_tokens_and_prevents_self_demote(app, make_user, login, outbox):
    admin = make_user("admin", email="root@test.com")
    agent = make_user("agent", email="worker@test.com", department="Water Department")
    client = app.test_client()
    admin_headers = login("root@test.com")
    old_agent_headers = login("worker@test.com")

    assert client.get(f"/auth/users/{agent['id']}", headers=admin_headers).status_code == 200
    assert client.patch(f"/auth/users/{agent['id']}", json={"name": "Updated Worker"}, headers=admin_headers).get_json()["name"] == "Updated Worker"
    assert client.get("/auth/me", headers=old_agent_headers).status_code == 200
    assert client.patch(f"/auth/users/{admin['id']}", json={"active": False}, headers=admin_headers).status_code == 400

    assert client.delete(f"/auth/users/{agent['id']}", headers=admin_headers).status_code == 200
    assert client.get("/auth/me", headers=old_agent_headers).status_code == 401
    assert client.post("/auth/login", json={"email": "worker@test.com", "password": "password123"}).status_code == 401


def test_admin_creation_sends_welcome_without_password(app, make_user, login, outbox):
    make_user("admin", email="admin@test.com")
    headers = login("admin@test.com")
    response = app.test_client().post("/auth/users", json={
        "name": "New Agent", "email": "new-agent@test.com", "password": "secret123",
        "role": "agent", "department": "Water Department"
    }, headers=headers)
    assert response.status_code == 201
    assert any(message[1] == "new-agent@test.com" and "Welcome" in message[2] for message in outbox)
    assert all("secret123" not in message[3] for message in outbox)


def test_deactivating_agent_returns_open_work_to_supervisor(app, make_user, login, citizen):
    agent = make_user("agent", email="assigned@test.com", department="Water Department")
    make_user("supervisor", email="supervisor@test.com")
    admin = make_user("admin", email="admin@test.com")
    client = app.test_client()
    complaint = client.post("/submit-complaint", json=complaint_body(category="Water Supply"), headers=citizen).get_json()
    # Force this test complaint onto the target agent.
    items = cr._load()
    stored = next(item for item in items if item["id"] == complaint["id"])
    stored["assigned_to"] = agent["id"]
    cr._save(items)

    result = client.delete(f"/auth/users/{agent['id']}", headers=login("admin@test.com"))
    assert result.status_code == 200
    stored = next(item for item in cr._load() if item["id"] == complaint["id"])
    assert stored["assigned_to"] is None and stored["needs_supervisor"] is True and stored["status"] == "New"


def test_malformed_json_and_non_object_body_return_400(app):
    client = app.test_client()
    assert client.post("/auth/login", data="[1,2]", content_type="application/json").status_code == 400
    assert client.post("/auth/login", data="{bad json", content_type="application/json").status_code == 400


def test_citizen_complaint_view_redacts_internal_escalation_data(app, make_user, login, citizen):
    make_user("agent", email="agent@test.com", department="Water Department")
    make_user("supervisor", email="supervisor@test.com")
    complaint = app.test_client().post("/submit-complaint", json=complaint_body(category="Water Supply"), headers=citizen).get_json()
    items = cr._load()
    stored = next(item for item in items if item["id"] == complaint["id"])
    stored["escalated"] = True
    stored["alerts"] = [{"message": "internal SLA alert"}]
    stored["escalations"] = [{"reason": "internal reason", "from_agent": "U-private", "to_agent": "U-private2"}]
    cr._save(items)
    visible = app.test_client().get(f"/complaints/{complaint['id']}", headers=citizen).get_json()
    assert visible["escalated"] is True
    assert "alerts" not in visible and "escalations" not in visible


def test_async_notifications_queue_delivery_and_update_status(app, make_user, monkeypatch):
    user = make_user(email="async@test.com")
    completed = threading.Event()
    monkeypatch.setenv("NOTIFY_ASYNC", "1")

    def fake_send(*_args):
        completed.set()
        return "sent"

    monkeypatch.setattr(notifications, "send_email", fake_send)
    records = notifications.notify([user["id"]], "submitted", "Queued notification")
    assert records[0]["delivery"]["in_app"] == "delivered"
    assert records[0]["delivery"]["email"] == "queued"
    assert completed.wait(3)
    latest = None
    for _ in range(40):
        latest = next(item for item in notifications._load() if item["id"] == records[0]["id"])
        if latest["delivery"]["email"] == "sent":
            break
        time.sleep(0.025)
    assert latest["delivery"]["email"] == "sent"
