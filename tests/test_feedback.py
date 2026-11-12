"""Sprint 3 Task 2 (issue #27): resolution rating, feedback and auto-close. FR-008, FR-011, UC-03, TC14, TC15."""
from datetime import datetime, timedelta, timezone

import pytest

import routes.complaint_routes as cr
from conftest import complaint_body
from services import analytics, feedback


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


def resolve(c, cid, hdr):
    move(c, cid, "In Progress", hdr["agent"])
    assert move(c, cid, "Resolved", hdr["agent"], note="Replaced the valve").status_code == 200


def rate(c, cid, headers, rating, comment=None):
    return c.post(f"/complaints/{cid}/feedback", json={"rating": rating, "comment": comment}, headers=headers)


def age_resolution(cid, days):
    """Pretend the latest resolution happened `days` ago."""
    items = cr._load()
    comp = next(i for i in items if i["id"] == cid)
    last = max(i for i, h in enumerate(comp["history"]) if h["status"] == "Resolved")
    comp["history"][last]["at"] = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cr._save(items)


def stored(cid):
    return next(i for i in cr._load() if i["id"] == cid)


# ---------- rating (TC14) ----------
def test_rating_saves_feedback_and_closes_complaint(setup):
    c, cid, hdr = setup
    resolve(c, cid, hdr)
    r = rate(c, cid, hdr["citizen"], 4, "  Fixed quickly, thanks  ")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "Closed" and body["rating"] == 4
    assert body["feedback"]["rating"] == 4 and body["feedback"]["comment"] == "Fixed quickly, thanks"
    last = body["history"][-1]
    assert last["status"] == "Closed" and last["by"] == body["citizen_id"] and last["note"].startswith("Rated 4/5")
    assert stored(cid)["feedback"]["rating"] == 4


def test_rating_without_comment_is_accepted(setup):
    c, cid, hdr = setup
    resolve(c, cid, hdr)
    r = rate(c, cid, hdr["citizen"], 5)
    assert r.status_code == 200 and r.get_json()["feedback"]["comment"] is None


@pytest.mark.parametrize("bad", [0, 6, -1, 4.5, "4", "text", True, None, [5]])
def test_invalid_ratings_are_rejected(setup, bad):
    c, cid, hdr = setup
    resolve(c, cid, hdr)
    r = rate(c, cid, hdr["citizen"], bad)
    assert r.status_code == 400 and "whole number from 1 to 5" in r.get_json()["error"]
    assert stored(cid)["status"] == "Resolved" and "feedback" not in stored(cid)


def test_comment_limit_is_500_characters(setup):
    c, cid, hdr = setup
    resolve(c, cid, hdr)
    assert rate(c, cid, hdr["citizen"], 3, "x" * 501).status_code == 400
    assert rate(c, cid, hdr["citizen"], 3, 42).status_code == 400
    assert rate(c, cid, hdr["citizen"], 3, "x" * 500).status_code == 200


def test_only_the_owner_can_rate(setup):
    c, cid, hdr = setup
    resolve(c, cid, hdr)
    assert rate(c, cid, hdr["other"], 1).status_code == 403
    assert rate(c, cid, hdr["agent"], 5).status_code == 403          # staff cannot rate at all
    assert rate(c, "SCMS-00000000-00000", hdr["citizen"], 5).status_code == 404
    assert stored(cid)["status"] == "Resolved"


def test_can_rate_only_once(setup):
    c, cid, hdr = setup
    resolve(c, cid, hdr)
    assert rate(c, cid, hdr["citizen"], 2).status_code == 200
    r = rate(c, cid, hdr["citizen"], 5)
    assert r.status_code == 409 and "already been rated" in r.get_json()["error"]
    assert stored(cid)["rating"] == 2


def test_only_resolved_complaints_can_be_rated(setup):
    c, cid, hdr = setup
    move(c, cid, "In Progress", hdr["agent"])
    r = rate(c, cid, hdr["citizen"], 5)
    assert r.status_code == 409 and "resolved" in r.get_json()["error"]


def test_rating_after_the_7_day_window_is_rejected(setup):
    c, cid, hdr = setup
    resolve(c, cid, hdr)
    age_resolution(cid, 7.01)
    r = rate(c, cid, hdr["citizen"], 5)
    assert r.status_code == 409 and "7-day" in r.get_json()["error"]


def test_rating_on_day_6_is_accepted(setup):
    c, cid, hdr = setup
    resolve(c, cid, hdr)
    age_resolution(cid, 6)
    assert rate(c, cid, hdr["citizen"], 5).status_code == 200


def test_reopened_complaint_gets_a_new_window(setup):
    c, cid, hdr = setup
    resolve(c, cid, hdr)
    age_resolution(cid, 10)                                            # first window long gone
    assert move(c, cid, "In Progress", hdr["citizen"], note="Still leaking").status_code == 200
    assert move(c, cid, "Resolved", hdr["agent"], note="Replaced the pipe section").status_code == 200
    assert rate(c, cid, hdr["citizen"], 4).status_code == 200


def test_agent_is_told_the_rating(setup, app):
    c, cid, hdr = setup
    resolve(c, cid, hdr)
    rate(c, cid, hdr["citizen"], 3, "Took a while")
    latest = c.get("/notifications/data", headers=hdr["agent"]).get_json()["items"][0]
    assert "Closed" in latest["message"] and "Rated 3/5: Took a while" in latest["message"]


def test_resolution_notification_asks_for_a_rating(setup):
    c, cid, hdr = setup
    resolve(c, cid, hdr)
    latest = c.get("/notifications/data", headers=hdr["citizen"]).get_json()["items"][0]
    assert latest["type"] == "resolution" and "rate the resolution (1-5) within 7 days" in latest["message"]


# ---------- auto-close (TC15) ----------
def test_unrated_resolution_auto_closes_after_7_days(setup, make_user, login):
    c, cid, hdr = setup
    make_user("supervisor", email="sup@test.com")
    resolve(c, cid, hdr)
    age_resolution(cid, 7.01)
    assert c.post("/sla/check", headers=login("sup@test.com")).status_code == 200
    comp = stored(cid)
    assert comp["status"] == "Closed" and comp["auto_closed"] is True and "feedback" not in comp
    assert comp["history"][-1]["by"] == "system" and "no feedback within 7 days" in comp["history"][-1]["note"]
    latest = c.get("/notifications/data", headers=hdr["citizen"]).get_json()["items"][0]
    assert "is now Closed" in latest["message"]
    assert rate(c, cid, hdr["citizen"], 5).status_code == 409        # too late to rate once auto-closed


def test_auto_close_leaves_recent_rated_and_reopened_complaints_alone(setup):
    c, cid, hdr = setup
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=8)).isoformat()
    recent = (now - timedelta(days=6)).isoformat()
    items = [
        {"id": "A", "status": "Resolved", "history": [{"status": "Resolved", "at": recent}]},
        {"id": "B", "status": "Closed", "feedback": {"rating": 5}, "history": [{"status": "Resolved", "at": old}]},
        {"id": "C", "status": "In Progress", "history": [{"status": "Resolved", "at": old}, {"status": "In Progress", "at": recent}]},
        {"id": "D", "status": "Resolved", "history": [{"status": "Resolved", "at": old}]},
    ]
    closed = feedback.auto_close(items, now)
    assert [x["id"] for x in closed] == ["D"]
    assert [x["status"] for x in items] == ["Resolved", "Closed", "In Progress", "Closed"]


def test_window_counts_from_the_latest_resolution():
    t1 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 5, tzinfo=timezone.utc)
    comp = {"history": [{"status": "Resolved", "at": t1.isoformat()}, {"status": "In Progress", "at": t1.isoformat()},
                        {"status": "Resolved", "at": t2.isoformat()}]}
    assert feedback.window_ends(comp) == t2 + timedelta(days=7)
    assert feedback.window_ends({"history": []}) is None


# ---------- dashboard CSAT (FR-011) ----------
def test_csat_trend_averages_ratings_per_day():
    comps = [{"feedback": {"rating": 5, "at": "2026-11-10T09:00:00+00:00"}},
             {"feedback": {"rating": 2, "at": "2026-11-10T18:00:00+00:00"}},
             {"feedback": {"rating": 4, "at": "2026-11-09T12:00:00+00:00"}},
             {"status": "Closed", "auto_closed": True}]
    assert feedback.csat_trend(comps) == [{"date": "2026-11-09", "average": 4.0, "count": 1},
                                          {"date": "2026-11-10", "average": 3.5, "count": 2}]
    assert feedback.csat_trend([]) == []


def test_dashboard_shows_csat_and_trend_after_rating(setup, make_user, login):
    c, cid, hdr = setup
    make_user("supervisor", email="sup@test.com")
    sup = login("sup@test.com")
    assert c.get("/dashboard/data", headers=sup).get_json()["csat"] is None
    resolve(c, cid, hdr)
    rate(c, cid, hdr["citizen"], 4)
    d = c.get("/dashboard/data", headers=sup).get_json()
    today = datetime.now(timezone.utc).date().isoformat()
    assert d["csat"] == 4.0 and d["csat_trend"] == [{"date": today, "average": 4.0, "count": 1}]
    assert analytics.kpis([])["csat_trend"] == []
