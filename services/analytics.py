"""Issue #12: KPI calculations for the supervisor / admin dashboard."""
from collections import Counter
from datetime import datetime

from services import sla

OPEN_STATES = {"New", "Assigned", "In Progress", "Pending Info"}
DONE_STATES = {"Resolved", "Closed"}


def apply_filters(complaints, date_from=None, date_to=None, department=None, agent=None):
    out = []
    for c in complaints:
        day = c["created_at"][:10]
        if date_from and day < date_from:
            continue
        if date_to and day > date_to:
            continue
        if department and c.get("department") != department:
            continue
        if agent and c.get("assigned_to") != agent:
            continue
        out.append(c)
    return out


def _hours_to_resolve(c):
    r = sla.resolved_at(c)
    return (r - datetime.fromisoformat(c["created_at"])).total_seconds() / 3600 if r else None


def kpis(complaints, now=None):
    durations = [h for h in (_hours_to_resolve(c) for c in complaints) if h is not None]
    ratings = [c["rating"] for c in complaints if isinstance(c.get("rating"), (int, float))]
    return {
        "total": len(complaints),
        "open": sum(1 for c in complaints if c.get("status") in OPEN_STATES),
        "resolved": sum(1 for c in complaints if c.get("status") in DONE_STATES),
        "overdue": sum(1 for c in complaints if sla.is_overdue(c, now)),
        "avg_resolution_hours": round(sum(durations) / len(durations), 1) if durations else None,
        "sla_compliance_percent": sla.compliance(complaints),
        "csat": round(sum(ratings) / len(ratings), 2) if ratings else None,   # average 1-5 rating
        "by_status": dict(Counter(c.get("status", "New") for c in complaints)),
        "by_category": dict(Counter(c.get("category") for c in complaints)),
        "by_department": dict(Counter(c.get("department") for c in complaints)),
    }


REPORT_COLUMNS = ["id", "title", "category", "department", "severity", "status",
                  "assigned_to", "created_at", "due_at", "overdue", "resolution_hours", "rating"]


def report_rows(complaints, now=None):
    for c in complaints:
        h = _hours_to_resolve(c)
        yield [c["id"], c.get("title", ""), c.get("category", ""), c.get("department", ""), c.get("severity", ""),
               c.get("status", ""), c.get("assigned_to") or "", c["created_at"], (c.get("sla") or {}).get("due_at", ""),
               "yes" if sla.is_overdue(c, now) else "no", "" if h is None else round(h, 1), c.get("rating", "")]
