"""Issue #7: Agent resolution management - work queue, internal notes and resolving complaints.

Resolving needs resolution notes (FR-013). Internal notes carry author and timestamp and are staff-only (FR-014).
"""
from datetime import datetime, timezone

from services import sla
from services import status as lifecycle

MAX_NOTE = 2000
ACTIVE_STATES = ("Assigned", "In Progress", "Pending Info")
DONE_STATES = ("Resolved", "Closed")
QUEUE_FIELDS = ("id", "title", "category", "department", "severity", "status", "created_at")
NEVER = datetime.max.replace(tzinfo=timezone.utc)


def can_manage(user, complaint):
    """Assigned agent, or any supervisor / admin."""
    if user["role"] in ("supervisor", "admin"):
        return True
    return user["role"] == "agent" and complaint.get("assigned_to") == user["id"]


def _clean(value, missing):
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise ValueError(missing)
    if len(text) > MAX_NOTE:
        raise ValueError(f"Notes must be at most {MAX_NOTE} characters")
    return text


def add_note(complaint, user, text):
    """Add a timestamped internal note signed by `user`. Returns the new note."""
    if complaint.get("status") == "Closed":
        raise ValueError("Notes cannot be added to a closed complaint")
    notes = complaint.setdefault("notes", [])
    note = {"id": f"N{len(notes) + 1}", "text": _clean(text, "Note text is required"),
            "by": user["id"], "by_name": user["name"], "at": datetime.now(timezone.utc).isoformat()}
    notes.append(note)
    return note


def change_status(complaint, user, new_status, note=None):
    """Lifecycle change in which resolving requires resolution notes, kept on the complaint."""
    if new_status == "Resolved":
        note = _clean(note, "Resolution notes are required to resolve a complaint")
    lifecycle.change(complaint, new_status, user["id"], note)
    if new_status == "Resolved":
        complaint["resolution"] = {"notes": note, "by": user["id"], "by_name": user["name"],
                                   "at": complaint["history"][-1]["at"]}
    elif new_status == "In Progress":   # reopened, so the earlier resolution no longer applies
        complaint.pop("resolution", None)
    return complaint


def for_viewer(user, complaint):
    """Citizens never see internal notes."""
    if user["role"] != "citizen" or "notes" not in complaint:
        return complaint
    return {k: v for k, v in complaint.items() if k != "notes"}


def queue(complaints, agent_id, include_done=False, now=None):
    """Complaints assigned to the agent, most urgent SLA first so overdue ones are on top."""
    now = now or sla.now_utc()
    states = ACTIVE_STATES + DONE_STATES if include_done else ACTIVE_STATES
    rows = []
    for c in complaints:
        if c.get("assigned_to") != agent_id or c.get("status") not in states:
            continue
        due = datetime.fromisoformat(c["sla"]["due_at"]) if c.get("sla") else None
        row = {k: c.get(k) for k in QUEUE_FIELDS}
        row.update(due_at=due.isoformat() if due else None, overdue=sla.is_overdue(c, now),
                   minutes_left=int((due - now).total_seconds() // 60) if due else None)
        rows.append(((row["status"] in DONE_STATES, due or NEVER), row))
    return [row for _, row in sorted(rows, key=lambda r: r[0])]
