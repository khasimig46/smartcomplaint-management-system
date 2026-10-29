"""Issue #6: Complaint lifecycle and status history.

New -> Assigned -> In Progress -> Pending Info -> Resolved -> Closed
"""
from datetime import datetime, timezone

STATUSES = ("New", "Assigned", "In Progress", "Pending Info", "Resolved", "Closed")
TRANSITIONS = {
    "New": {"Assigned"},
    "Assigned": {"In Progress"},
    "In Progress": {"Pending Info", "Resolved"},
    "Pending Info": {"In Progress"},
    "Resolved": {"Closed", "In Progress"},   # citizen may reopen if not fixed
    "Closed": set(),
}


class TransitionError(Exception):
    pass


def _entry(status, by, note=None):
    return {"status": status, "at": datetime.now(timezone.utc).isoformat(), "by": by, "note": note}


def start(complaint, citizen_id):
    """Initialise lifecycle on a new complaint (and record auto-assignment)."""
    complaint["status"] = "New"
    complaint["history"] = [_entry("New", citizen_id, "Complaint submitted")]
    if complaint.get("assigned_to"):
        change(complaint, "Assigned", "system", f"Auto-assigned to {complaint['assigned_to']} ({complaint['department']})")


def change(complaint, new_status, by, note=None):
    current = complaint.get("status", "New")
    if new_status not in STATUSES:
        raise TransitionError(f"Unknown status '{new_status}'")
    if new_status not in TRANSITIONS[current]:
        raise TransitionError(f"Cannot move from '{current}' to '{new_status}'")
    complaint["status"] = new_status
    complaint.setdefault("history", []).append(_entry(new_status, by, note))
    return complaint


def allowed_by(user, complaint, new_status):
    """Who may make which transition."""
    role = user["role"]
    if role in ("supervisor", "admin"):
        return True
    if role == "agent":
        return complaint.get("assigned_to") == user["id"] and new_status in ("In Progress", "Pending Info", "Resolved")
    if role == "citizen":  # citizen closes or reopens their own resolved complaint
        return complaint.get("citizen_id") == user["id"] and complaint.get("status") == "Resolved" \
            and new_status in ("Closed", "In Progress")
    return False
