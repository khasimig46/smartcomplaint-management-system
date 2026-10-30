"""Issue #10: Supervisors escalate stalled complaints to a priority queue with a new SLA.

Escalating hands the ticket to the least-loaded agent of the receiving team (preferring someone other than
the current assignee), restarts the SLA timer from the escalation time and marks the ticket as priority.
"""
from datetime import datetime

from services import routing, sla
from services import status as lifecycle

STALLED_HOURS = 48
MAX_REASON = 500
OPEN_STATES = ("New", "Assigned", "In Progress", "Pending Info")
TEAMS = tuple(dict.fromkeys([*routing.DEPARTMENTS.values(), routing.DEFAULT_DEPARTMENT]))


def last_activity(complaint):
    stamps = [x["at"] for key in ("history", "notes", "escalations") for x in complaint.get(key, [])]
    return max(map(datetime.fromisoformat, stamps), default=datetime.fromisoformat(complaint["created_at"]))


def pick_agent(department, users, complaints, current=None, zone=None):
    """Least-loaded active agent of the team, preferring a fresh pair of eyes over the current assignee."""
    agents = [u for u in users if u["role"] == "agent" and u.get("active", True) and u.get("department") == department]
    agents = [a for a in agents if a["id"] != current] or agents
    if zone:
        agents = [a for a in agents if a.get("zone") == zone] or agents
    if not agents:
        return None
    return min(agents, key=lambda a: (routing.open_load(a["id"], complaints), a["created_at"]))["id"]


def escalate(complaint, user, reason, department, users, complaints, now=None):
    """Move the complaint to the priority queue of `department` with a new SLA. Returns the escalation record."""
    if complaint.get("status") not in OPEN_STATES:
        raise ValueError("Only open complaints can be escalated")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not reason:
        raise ValueError("A reason for the escalation is required")
    if len(reason) > MAX_REASON:
        raise ValueError(f"Reason must be at most {MAX_REASON} characters")
    department = department or complaint.get("department")
    if department not in TEAMS:
        raise ValueError("Unknown receiving team")
    previous = complaint.get("assigned_to")
    others = [c for c in complaints if c["id"] != complaint["id"]]
    agent = pick_agent(department, users, others, current=previous, zone=complaint.get("zone"))
    if not agent:
        raise ValueError(f"No active agent is available in {department}")

    now = now or sla.now_utc()
    record = {"at": now.isoformat(), "by": user["id"], "by_name": user["name"], "reason": reason,
              "from_department": complaint.get("department"), "to_department": department,
              "from_agent": previous, "to_agent": agent, "previous_due_at": (complaint.get("sla") or {}).get("due_at")}
    complaint.update(department=department, assigned_to=agent, needs_supervisor=False, escalated=True)
    complaint.setdefault("escalations", []).append(record)
    sla.assign_deadline(complaint, start=now)
    if complaint["status"] == "New":
        lifecycle.change(complaint, "Assigned", user["id"], f"Escalated to {department}")
    return record


def _row(c, now):
    due = (c.get("sla") or {}).get("due_at")
    last = (c.get("escalations") or [{}])[-1]
    return {"id": c["id"], "title": c.get("title"), "severity": c.get("severity"), "status": c.get("status"),
            "department": c.get("department"), "assigned_to": c.get("assigned_to"), "due_at": due,
            "overdue": sla.is_overdue(c, now), "escalations": len(c.get("escalations", [])),
            "last_reason": last.get("reason"), "idle_hours": round((now - last_activity(c)).total_seconds() / 3600, 1)}


def priority_queue(complaints, now=None):
    """Open escalated complaints, nearest new deadline first."""
    now = now or sla.now_utc()
    rows = [_row(c, now) for c in complaints if c.get("escalated") and c.get("status") in OPEN_STATES]
    return sorted(rows, key=lambda r: datetime.fromisoformat(r["due_at"]) if r["due_at"] else now)


def stalled(complaints, now=None):
    """Open complaints a supervisor should look at: overdue, unassigned, or idle for STALLED_HOURS."""
    now = now or sla.now_utc()
    rows = []
    for c in complaints:
        if c.get("status") not in OPEN_STATES:
            continue
        row = _row(c, now)
        row["unassigned"] = not c.get("assigned_to")
        if row["overdue"] or row["unassigned"] or row["idle_hours"] >= STALLED_HOURS:
            rows.append(row)
    return sorted(rows, key=lambda r: (not r["overdue"], -r["idle_hours"]))
