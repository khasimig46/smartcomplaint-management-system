"""Load demo accounts and complaints so every screen has something to show.

    python scripts/seed_demo.py            # refuses if data already exists
    python scripts/seed_demo.py --reset    # deletes ALL local data first (complaints, users, notifications,
                                           # SLA rules, audit log, uploads), then seeds

Everything goes through the real API (routing, SLA, notifications, audit log all run). Afterwards some
timestamps are moved into the past so the demo has an overdue complaint, a stalled one, a resolution
waiting for a rating and one that was auto-closed. Those backdated times are in the complaint records
only; the audit log keeps the real time each action was seeded.

Email/SMS are only sent if SMTP_HOST / TWILIO_* are set, so unset them before seeding.
"""
import argparse
import os
import shutil
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

PASSWORD = "Demo@2026"
DATA_FILES = ["data/complaints_store.json", "data/users.json", "data/notifications.json", "data/sla_rules.json",
              "data/audit_log.jsonl"]

STAFF = [  # name, email, role, department, zone
    ("Sunita Rao", "supervisor@demo.local", "supervisor", None, None),
    ("Ravi Kumar", "water.agent@demo.local", "agent", "Water Department", "North"),
    ("Meera Shah", "water.agent2@demo.local", "agent", "Water Department", "South"),
    ("Arjun Nair", "roads.agent@demo.local", "agent", "Roads & Infrastructure", None),
    ("Priya Iyer", "power.agent@demo.local", "agent", "Electricity Department", None),
    ("Imran Khan", "sanitation.agent@demo.local", "agent", "Sanitation Department", None),
    ("Kavya Menon", "environment.agent@demo.local", "agent", "Environment Department", None),
    ("Rohan Das", "safety.agent@demo.local", "agent", "Public Safety Department", None),
    ("Neha Joshi", "general.agent@demo.local", "agent", "General Administration", None),
]
CITIZENS = [("Asha Verma", "asha@demo.local"), ("Vikram Singh", "vikram@demo.local")]


def ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reset", action="store_true", help="delete all local data before seeding")
    args = ap.parse_args()

    existing = [f for f in DATA_FILES if (ROOT / f).exists() and (ROOT / f).stat().st_size > 2]
    if existing and not args.reset:
        sys.exit(f"Data already exists ({', '.join(existing)}). Run with --reset to wipe it and seed again.")
    if args.reset:
        for f in DATA_FILES:
            (ROOT / f).unlink(missing_ok=True)
        shutil.rmtree(ROOT / "uploads", ignore_errors=True)

    os.environ.setdefault("ADMIN_EMAIL", "admin@demo.local")
    os.environ.setdefault("ADMIN_PASSWORD", PASSWORD)
    from app import create_app
    from routes import complaint_routes as cr
    from routes import sla_routes
    from services import auth

    app = create_app()
    c = app.test_client()
    with app.app_context():
        for name, email, role, dept, zone in STAFF:
            auth.create_user(name, email, PASSWORD, role=role, department=dept, zone=zone)

    def login(email, password=PASSWORD):
        r = c.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, (email, r.get_json())
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    for name, email in CITIZENS:
        assert c.post("/auth/register", json={"name": name, "email": email, "password": PASSWORD}).status_code == 201
    asha, vikram = login("asha@demo.local"), login("vikram@demo.local")
    staff = {e: login(e) for _, e, *_ in STAFF}
    sup = staff["supervisor@demo.local"]
    users = {u["id"]: u["email"] for u in auth.load_users()}

    def submit(who, title, desc, severity, category, zone=None):
        body = {"title": title, "description": desc, "severity": severity, "category": category}
        if zone:
            body["zone"] = zone
        r = c.post("/submit-complaint", json=body, headers=who)
        assert r.status_code == 201, r.get_json()
        return r.get_json()

    def agent_of(comp):
        return staff[users[comp["assigned_to"]]]

    def move(comp, status, who, note=None):
        r = c.patch(f"/complaints/{comp['id']}/status", json={"status": status, "note": note}, headers=who)
        assert r.status_code == 200, (comp["id"], status, r.get_json())

    # 1. Fresh complaint, just assigned
    c1 = submit(asha, "Water leakage near 5th Cross", "Pipe burst near the bus stop, water flooding the road "
                "since morning.", "High", "Water Supply", zone="North")
    # 2. In progress, with an internal note
    c2 = submit(asha, "Large pothole on MG Road", "Deep pothole in the left lane near the signal; two-wheelers "
                "are swerving into traffic.", "Medium", "Roads")
    move(c2, "In Progress", agent_of(c2))
    c.post(f"/complaints/{c2['id']}/notes", json={"text": "Patch crew booked for Thursday."}, headers=agent_of(c2))
    # 3. Waiting for the citizen (Pending Info) -> demo the reply
    c3 = submit(vikram, "Streetlight not working", "The streetlight outside our building has been off for a "
                "week; the lane is completely dark at night.", "High", "Electricity")
    move(c3, "In Progress", agent_of(c3))
    move(c3, "Pending Info", agent_of(c3), "Which pole number is it? It is painted on the pole at eye level.")
    # 4. Resolved, waiting for a rating -> demo the rating
    c4 = submit(asha, "Garbage not collected for 4 days", "Bins on 3rd Main are overflowing and stray dogs are "
                "spreading the waste.", "Medium", "Sanitation")
    move(c4, "In Progress", agent_of(c4))
    move(c4, "Resolved", agent_of(c4), "Collected all bins and added 3rd Main to the daily route.")
    # 5. Closed with a rating -> CSAT on the dashboard
    c5 = submit(vikram, "Loud construction after 10 pm", "Site on 12th Cross runs concrete mixers until "
                "midnight every day.", "Low", "Noise Pollution")
    move(c5, "In Progress", agent_of(c5))
    move(c5, "Resolved", agent_of(c5), "Site issued a notice; work now stops at 9 pm.")
    assert c.post(f"/complaints/{c5['id']}/feedback", json={"rating": 4, "comment": "Quiet now, thanks."},
                  headers=vikram).status_code == 200
    # 6. Critical and overdue -> SLA breach alert, top of the escalation list
    c6 = submit(vikram, "Open manhole on school road", "Manhole cover missing outside the primary school gate; "
                "children walk past it every morning.", "Critical", "Public Safety")
    move(c6, "In Progress", agent_of(c6))
    # 7. Resolved 8 days ago and never rated -> auto-closed by the monitor
    c7 = submit(asha, "Low water pressure in the evenings", "Water pressure drops to almost nothing between "
                "6 and 9 pm.", "Low", "Water Supply", zone="South")
    move(c7, "In Progress", agent_of(c7))
    move(c7, "Resolved", agent_of(c7), "Valve on the feeder line was half closed; opened fully.")
    # 8. Stalled: nobody has touched it for 3 days
    c8 = submit(asha, "Broken footpath tiles", "Loose tiles on the footpath near the park entrance; an elderly "
                "man tripped yesterday.", "Medium", "Roads")
    move(c8, "In Progress", agent_of(c8))

    # Move times into the past (complaint records only)
    with app.app_context():
        items = cr._load()
        by_id = {x["id"]: x for x in items}

        def backdate(cid, created_hours, history_hours, due_hours_from_now=None):
            x = by_id[cid]
            x["created_at"] = ago(hours=created_hours)
            for h, hrs in zip(x["history"], history_hours):
                h["at"] = ago(hours=hrs)
            if due_hours_from_now is not None:
                x["sla"]["due_at"] = (datetime.now(timezone.utc) + timedelta(hours=due_hours_from_now)).isoformat()
            if x.get("feedback"):
                x["feedback"]["at"] = x["history"][-1]["at"]

        backdate(c2["id"], 30, [30, 30, 26])
        backdate(c4["id"], 52, [52, 52, 40, 20])
        backdate(c5["id"], 120, [120, 120, 100, 80, 75])
        backdate(c6["id"], 7, [7, 7, 6], due_hours_from_now=-3)        # due 4 h after creation -> 3 h overdue
        backdate(c7["id"], 240, [240, 240, 220, 200])                  # resolved ~8.3 days ago
        backdate(c8["id"], 80, [80, 80, 72])                           # idle 72 h -> stalled
        cr._save(items)
        sla_routes.run_check()   # breach alert for #6 and auto-close #7 now, not a minute into the demo

    print("\nDemo data loaded. Password for every account below:", PASSWORD, "\n")
    print(f"  {'admin':<11} {os.environ['ADMIN_EMAIL']}")
    for name, email, role, dept, _ in STAFF:
        print(f"  {role:<11} {email:<32} {dept or ''}")
    for name, email in CITIZENS:
        print(f"  {'citizen':<11} {email}")
    print("\nComplaints:")
    for x in cr._load():
        print(f"  {x['id']}  {x['status']:<12} {x['category']:<16} {x['title']}")
    print("\nStart the app with:  python app.py   (not 'flask run': that skips the SLA monitor)")


if __name__ == "__main__":
    main()
