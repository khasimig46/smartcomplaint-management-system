"""Sprint 3 Task 3 (issue #28): immutable audit log (FR-012, UC-11 step 6, UC-12 step 6).

Every complaint action, login and admin change is appended to data/audit_log.jsonl, one JSON entry per line.
Entries are hash-chained: each stores the SHA-256 of the previous entry, and its own hash covers all of its fields.
Editing, deleting, reordering or inserting a line breaks the chain, which verify() reports.

Limitation: the chain detects tampering, it does not prevent it. Someone with write access to the file could
rewrite the whole chain from the edited line onwards. Production use would anchor the latest hash somewhere the
application cannot write (a separate log service, WORM storage or a signed checkpoint).
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from services import storage

LOG = Path(__file__).resolve().parent.parent / "data" / "audit_log.jsonl"
GENESIS = "0" * 64
SYSTEM = "system"


def _digest(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read():
    if not LOG.exists():
        return []
    with LOG.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _last():
    """(seq, hash) of the last entry, reading only the tail of the file."""
    if not LOG.exists() or LOG.stat().st_size == 0:
        return 0, GENESIS
    with LOG.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        block = min(size, 64 * 1024)
        f.seek(size - block)
        last = [line for line in f.read().splitlines() if line.strip()][-1]
    entry = json.loads(last)
    return entry["seq"], entry["hash"]


@storage.synchronized
def record(action, actor, complaint_id=None, **details):
    """Append one entry. `actor` is a user ID, "system", or None for an unidentified caller (failed login)."""
    seq, prev = _last()
    entry = {"seq": seq + 1, "at": datetime.now(timezone.utc).isoformat(), "actor": actor, "action": action,
             "complaint_id": complaint_id, "details": details, "prev_hash": prev}
    entry["hash"] = _digest(entry)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:      # append only: there is no update or delete in this module or the API
        f.write(json.dumps(entry, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return entry


def entries(complaint_id=None, actor=None, action=None):
    return [e for e in _read()
            if (complaint_id is None or e["complaint_id"] == complaint_id)
            and (actor is None or e["actor"] == actor)
            and (action is None or e["action"] == action)]


def verify():
    """Walk the chain. Returns {"ok", "entries", "problem", "seq"}; seq is the first bad entry's position."""
    prev, n = GENESIS, 0
    try:
        lines = [line for line in LOG.read_text().splitlines() if line.strip()] if LOG.exists() else []
    except OSError as e:
        return {"ok": False, "entries": 0, "problem": f"Cannot read the audit log: {e}", "seq": None}
    for n, line in enumerate(lines, 1):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            return {"ok": False, "entries": len(lines), "problem": "Entry is not valid JSON", "seq": n}
        if e.get("seq") != n:
            return {"ok": False, "entries": len(lines), "problem": "Entry missing or out of order", "seq": n}
        if e.get("prev_hash") != prev:
            return {"ok": False, "entries": len(lines), "problem": "Chain broken: previous entry was changed or removed",
                    "seq": n}
        if e.get("hash") != _digest(e):
            return {"ok": False, "entries": len(lines), "problem": "Entry was modified after it was written", "seq": n}
        prev = e["hash"]
    return {"ok": True, "entries": n, "problem": None, "seq": None}
