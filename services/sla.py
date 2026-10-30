"""Issue #9: SLA rules, deadlines, warning/breach alerts and compliance tracking."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

RULES_FILE = Path(__file__).resolve().parent.parent / "data" / "sla_rules.json"
DEFAULT_RULES = {"Critical": 4, "High": 24, "Medium": 72, "Low": 120}   # resolution hours by severity
WARNING_HOURS = 2
DONE_STATES = {"Resolved", "Closed"}


def now_utc():
    return datetime.now(timezone.utc)


def _parse(ts):
    return datetime.fromisoformat(ts)


# ---------- rules ----------
def load_rules():
    rules = dict(DEFAULT_RULES)
    if RULES_FILE.exists():
        rules.update(json.loads(RULES_FILE.read_text()))
    return rules


def save_rules(updates):
    rules = load_rules()
    for severity, hours in updates.items():
        if severity not in DEFAULT_RULES:
            raise ValueError(f"Unknown severity '{severity}'")
        if not isinstance(hours, (int, float)) or isinstance(hours, bool) or hours <= 0:
            raise ValueError(f"Hours for {severity} must be a positive number")
        rules[severity] = hours
    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    RULES_FILE.write_text(json.dumps(rules, indent=2))
    return rules


# ---------- deadlines ----------
def assign_deadline(complaint, start=None):
    start = start or _parse(complaint["created_at"])
    hours = load_rules().get(complaint.get("severity"), DEFAULT_RULES["Medium"])
    complaint["sla"] = {"hours": hours, "started_at": start.isoformat(),
                        "due_at": (start + timedelta(hours=hours)).isoformat(),
                        "warned": False, "breached": False}
    return complaint


def resolved_at(complaint):
    for h in complaint.get("history", []):
        if h["status"] == "Resolved":
            return _parse(h["at"])
    return None


def is_overdue(complaint, now=None):
    sla = complaint.get("sla")
    if not sla or complaint.get("status") in DONE_STATES:
        return False
    return (now or now_utc()) > _parse(sla["due_at"])


def _alert(complaint, kind, to, at, message):
    complaint.setdefault("alerts", []).append(
        {"type": kind, "to": to, "at": at.isoformat(), "message": message, "complaint_id": complaint["id"]})


def check(complaints, now=None):
    """Scan open complaints; add warning / breach alerts once each. Returns new alerts."""
    now = now or now_utc()
    new = []
    for c in complaints:
        sla = c.get("sla")
        if not sla or c.get("status") in DONE_STATES:
            continue
        due = _parse(sla["due_at"])
        remaining = due - now
        if remaining <= timedelta(0) and not sla["breached"]:
            sla["breached"] = True
            _alert(c, "breach", "supervisor", now, f"SLA breached for {c['id']} (due {due:%d %b %H:%M} UTC)")
            new.append(c["alerts"][-1])
        elif timedelta(0) < remaining <= timedelta(hours=WARNING_HOURS) and not sla["warned"]:
            sla["warned"] = True
            _alert(c, "warning", c.get("assigned_to") or "supervisor", now,
                   f"{c['id']} is due in {int(remaining.total_seconds() // 60)} minutes")
            new.append(c["alerts"][-1])
    return new


def compliance(complaints):
    """Share of resolved complaints that were resolved on or before their deadline."""
    done = [(c, resolved_at(c)) for c in complaints if c.get("sla") and resolved_at(c)]
    if not done:
        return None
    on_time = sum(1 for c, r in done if r <= _parse(c["sla"]["due_at"]))
    return round(100 * on_time / len(done), 1)


def violations(complaints, now=None):
    now = now or now_utc()
    out = []
    for c in complaints:
        sla = c.get("sla")
        if not sla:
            continue
        r = resolved_at(c)
        late = (r and r > _parse(sla["due_at"])) or (not r and is_overdue(c, now))
        if late or sla.get("breached"):
            out.append({"id": c["id"], "title": c.get("title"), "due_at": sla["due_at"],
                        "status": c.get("status"), "assigned_to": c.get("assigned_to")})
    return out
