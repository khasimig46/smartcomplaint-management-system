from datetime import datetime, timedelta, timezone

import routes.complaint_routes as cr
from conftest import complaint_body
from services import analytics, sla

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


def c(cid, status, dept="Water Department", agent="A1", hours_to_resolve=None, rating=None, created=T0):
    x = {"id": cid, "status": status, "department": dept, "assigned_to": agent, "category": "Water Supply",
         "severity": "High", "created_at": created.isoformat(), "history": []}
    if hours_to_resolve is not None:
        x["history"].append({"status": "Resolved", "at": (created + timedelta(hours=hours_to_resolve)).isoformat()})
    if rating:
        x["rating"] = rating
    return sla.assign_deadline(x)


DATA = [c("C1", "Assigned"), c("C2", "Resolved", hours_to_resolve=10, rating=4),
        c("C3", "Closed", hours_to_resolve=30, rating=2, dept="Roads & Infrastructure", agent="A2"),
        c("C4", "In Progress", created=T0 - timedelta(days=3))]


def test_kpis_are_accurate():
    k = analytics.kpis(DATA, now=T0 + timedelta(hours=1))
    assert (k["total"], k["open"], k["resolved"]) == (4, 2, 2)
    assert k["overdue"] == 1                       # C4 is 3 days old on a 24h SLA
    assert k["avg_resolution_hours"] == 20.0       # (10 + 30) / 2
    assert k["sla_compliance_percent"] == 50.0     # C2 on time, C3 late
    assert k["csat"] == 3.0
    assert k["by_department"] == {"Water Department": 3, "Roads & Infrastructure": 1}


def test_filters():
    assert [x["id"] for x in analytics.apply_filters(DATA, department="Roads & Infrastructure")] == ["C3"]
    assert [x["id"] for x in analytics.apply_filters(DATA, agent="A2")] == ["C3"]
    assert "C4" not in [x["id"] for x in analytics.apply_filters(DATA, date_from="2026-11-01")]


def test_empty_data_has_no_crashes():
    k = analytics.kpis([])
    assert k["total"] == 0 and k["avg_resolution_hours"] is None and k["csat"] is None


def test_dashboard_endpoint_and_permissions(app, make_user, login, citizen):
    make_user("supervisor", email="sup@test.com")
    cl = app.test_client()
    cl.post("/submit-complaint", json=complaint_body(), headers=citizen)
    assert cl.get("/dashboard/data", headers=citizen).status_code == 403
    d = cl.get("/dashboard/data", headers=login("sup@test.com")).get_json()
    assert d["total"] == 1 and d["open"] == 1 and "generated_at" in d


def test_report_generated_as_csv(app, make_user, login, citizen):
    make_user("admin", email="adm@test.com")
    cl = app.test_client()
    made = cl.post("/submit-complaint", json=complaint_body(), headers=citizen).get_json()
    r = cl.get("/dashboard/report.csv", headers=login("adm@test.com"))
    lines = r.get_data(as_text=True).strip().splitlines()
    assert r.mimetype == "text/csv" and lines[0].startswith("id,title") and lines[1].startswith(made["id"])


def test_dashboard_page_has_auto_refresh(app):
    html = app.test_client().get("/dashboard").get_data(as_text=True)
    assert "setInterval(load, 60000)" in html
