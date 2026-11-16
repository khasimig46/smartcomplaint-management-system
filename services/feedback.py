"""Sprint 3 Task 2 (issue #27): resolution rating, feedback and auto-close (FR-008, UC-03, FR-011 CSAT trend).

A citizen rates a Resolved complaint 1-5 with an optional comment, which closes it. The window is 7 days from the
latest resolution, so a reopened and re-resolved complaint gets a fresh window. Complaints left Resolved and unrated
past the window are closed by the system from the SLA monitor job.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from services import status as lifecycle

WINDOW_DAYS = 7
MAX_COMMENT = 500
MIN_RATING, MAX_RATING = 1, 5
SYSTEM = "system"


class FeedbackError(Exception):
    """The complaint cannot be rated right now (wrong state, already rated, or window closed)."""


def _now():
    return datetime.now(timezone.utc)


def latest_resolution(complaint):
    """Time of the most recent move to Resolved (a reopen + re-resolve starts a new window)."""
    times = [h["at"] for h in complaint.get("history", []) if h["status"] == "Resolved"]
    return datetime.fromisoformat(times[-1]) if times else None


def window_ends(complaint):
    resolved = latest_resolution(complaint)
    return resolved + timedelta(days=WINDOW_DAYS) if resolved else None


def validate(rating, comment):
    """Return (rating, comment) or raise ValueError. Only whole numbers 1-5; JSON true/false and "4" are rejected."""
    if isinstance(rating, bool) or not isinstance(rating, int) or not MIN_RATING <= rating <= MAX_RATING:
        raise ValueError(f"Rating must be a whole number from {MIN_RATING} to {MAX_RATING}")
    if comment is not None and not isinstance(comment, str):
        raise ValueError("Comment must be text")
    comment = (comment or "").strip() or None
    if comment and len(comment) > MAX_COMMENT:
        raise ValueError(f"Comment must be at most {MAX_COMMENT} characters")
    return rating, comment


def rate(complaint, user, rating, comment=None, now=None):
    """Save the citizen's rating and close the complaint (UC-03 postcondition).

    Raises PermissionError (not the owner), ValueError (bad input) or FeedbackError (cannot be rated now).
    """
    if complaint.get("citizen_id") != user["id"]:
        raise PermissionError("Only the citizen who raised this complaint can rate it")
    rating, comment = validate(rating, comment)
    if complaint.get("feedback"):
        raise FeedbackError("This complaint has already been rated")
    if complaint.get("status") != "Resolved":
        raise FeedbackError("Only a resolved complaint can be rated")
    now = now or _now()
    ends = window_ends(complaint)
    if ends and now > ends:
        raise FeedbackError(f"The {WINDOW_DAYS}-day feedback window for this resolution has ended")
    complaint["rating"] = rating   # the dashboard's CSAT already reads this field
    complaint["feedback"] = {"rating": rating, "comment": comment, "at": now.isoformat(), "by": user["id"]}
    lifecycle.change(complaint, "Closed", user["id"], f"Rated {rating}/5" + (f": {comment}" if comment else ""))
    return complaint


def auto_close(complaints, now=None):
    """Close complaints left Resolved and unrated for WINDOW_DAYS. Returns the closed complaints."""
    now = now or _now()
    closed = []
    for c in complaints:
        if c.get("status") != "Resolved" or c.get("feedback"):
            continue
        ends = window_ends(c)
        if ends and now >= ends:
            lifecycle.change(c, "Closed", SYSTEM, f"Closed automatically: no feedback within {WINDOW_DAYS} days")
            c["auto_closed"] = True
            closed.append(c)
    return closed


def csat_trend(complaints):
    """Average rating per day the feedback was given, oldest first (FR-011)."""
    days = defaultdict(list)
    for c in complaints:
        fb = c.get("feedback")
        if fb and isinstance(fb.get("rating"), int):
            days[fb["at"][:10]].append(fb["rating"])
    return [{"date": d, "average": round(sum(r) / len(r), 2), "count": len(r)} for d, r in sorted(days.items())]
