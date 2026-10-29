"""Issue #4: Unique, date-based ticket ID generation.

Format: SCMS-YYYYMMDD-NNNNN (e.g. SCMS-20261029-00001).
The 5-digit sequence restarts at 00001 each day and increases by one
for every complaint created that day.
"""
import re
import threading
from datetime import datetime, timezone

PREFIX = "SCMS"
PATTERN = re.compile(r"^SCMS-(\d{8})-(\d{5})$")
MAX_PER_DAY = 99999
_lock = threading.Lock()


def is_valid(ticket_id: str) -> bool:
    return bool(PATTERN.match(ticket_id or ""))


def generate_ticket_id(existing_ids, now: datetime | None = None) -> str:
    """Return the next unused ticket ID for today.

    existing_ids: iterable of IDs already issued (used to guarantee uniqueness).
    """
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y%m%d")
    with _lock:
        taken = set(existing_ids)
        seqs = [int(m.group(2)) for i in taken if (m := PATTERN.match(str(i))) and m.group(1) == day]
        seq = max(seqs, default=0) + 1
        if seq > MAX_PER_DAY:
            raise RuntimeError("Daily ticket limit reached")
        ticket = f"{PREFIX}-{day}-{seq:05d}"
        if ticket in taken:  # defensive: should be impossible after max()+1
            raise RuntimeError("Duplicate ticket ID generated")
        return ticket
