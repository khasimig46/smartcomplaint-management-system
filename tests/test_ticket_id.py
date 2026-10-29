from datetime import datetime, timezone

import pytest

import routes.complaint_routes as cr
from app import create_app
from services.ticket_id import generate_ticket_id, is_valid

DAY = datetime(2026, 10, 29, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "STORE", tmp_path / "store.json")
    return create_app().test_client()


def test_format_is_date_based():
    tid = generate_ticket_id([], now=DAY)
    assert tid == "SCMS-20261029-00001"
    assert is_valid(tid)


def test_sequence_increments_within_a_day():
    assert generate_ticket_id(["SCMS-20261029-00001", "SCMS-20261029-00002"], now=DAY) == "SCMS-20261029-00003"


def test_sequence_restarts_on_new_day():
    assert generate_ticket_id(["SCMS-20261028-00042"], now=DAY) == "SCMS-20261029-00001"


def test_no_duplicates_over_many_complaints():
    ids = []
    for _ in range(1000):
        ids.append(generate_ticket_id(ids, now=DAY))
    assert len(ids) == len(set(ids))


def test_submitted_complaint_gets_ticket_id(client):
    a = client.post("/submit-complaint", json={"text": "Water leakage near park"}).get_json()
    b = client.post("/submit-complaint", json={"text": "Pothole on main road"}).get_json()
    assert is_valid(a["id"]) and is_valid(b["id"])
    assert a["id"] != b["id"]
