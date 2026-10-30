"""Issue #11: In-app, email and SMS (opt-in) notifications for complaint updates.

Email is sent over SMTP when SMTP_HOST is set, SMS through Twilio when TWILIO_ACCOUNT_SID,
TWILIO_AUTH_TOKEN and TWILIO_FROM are set. Otherwise the message is written to the log.
"""
import base64
import json
import logging
import os
import re
import smtplib
import threading
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib import parse, request as urlrequest

from services import auth

STORE = Path(__file__).resolve().parent.parent / "data" / "notifications.json"
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")   # E.164, e.g. +919876543210
TIMEOUT = 10
SUBJECTS = {
    "submitted": "Complaint received",
    "assigned": "New complaint assigned to you",
    "needs_supervisor": "Complaint needs manual assignment",
    "status_update": "Complaint status updated",
    "resolution": "Complaint resolved",
    "sla_warning": "SLA deadline approaching",
    "sla_breach": "SLA breached",
}
log = logging.getLogger("scms.notifications")
_lock = threading.Lock()


def _load():
    return json.loads(STORE.read_text()) if STORE.exists() else []


def _save(items):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(items, indent=2))


# ---------- providers ----------
def send_email(to, subject, body):
    host = os.environ.get("SMTP_HOST")
    if not host:
        log.info("Email to %s: %s", to, subject)
        return "logged"
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM", "no-reply@scms.local")
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=TIMEOUT) as s:
        if os.environ.get("SMTP_TLS", "1") != "0":
            s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(msg)
    return "sent"


def send_sms(to, text):
    sid, token, sender = (os.environ.get(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"))
    if not (sid and token and sender):
        log.info("SMS to %s: %s", to, text)
        return "logged"
    req = urlrequest.Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                             data=parse.urlencode({"To": to, "From": sender, "Body": text}).encode())
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode())
    with urlrequest.urlopen(req, timeout=TIMEOUT) as r:
        r.read()
    return "sent"


def _deliver(send, *args):
    try:
        return send(*args)
    except Exception as e:   # a provider outage must not break the request that triggered it
        log.warning("Notification delivery failed: %s", e)
        return "failed"


# ---------- preferences ----------
def preferences(user):
    p = user.get("notify") or {}
    return {"email": p.get("email", True), "sms": p.get("sms", False), "phone": user.get("phone")}


def update_preferences(user_id, data):
    users = auth.load_users()
    user = next(u for u in users if u["id"] == user_id)
    prefs = preferences(user)
    if "phone" in data:
        phone = (data["phone"] or "").strip().replace(" ", "") or None
        if phone and not PHONE_RE.match(phone):
            raise ValueError("Phone must be in international format, e.g. +919876543210")
        prefs["phone"] = phone
    for channel in ("email", "sms"):
        if channel in data:
            if not isinstance(data[channel], bool):
                raise ValueError(f"'{channel}' must be true or false")
            prefs[channel] = data[channel]
    if prefs["sms"] and not prefs["phone"]:
        raise ValueError("A phone number is required for SMS notifications")
    user["phone"], user["notify"] = prefs["phone"], {"email": prefs["email"], "sms": prefs["sms"]}
    auth.save_users(users)
    return prefs


# ---------- sending ----------
def _email_body(message, complaint):
    if not complaint:
        return message
    lines = [message, "", f"Ticket: {complaint['id']}", f"Title: {complaint.get('title', '')}",
             f"Status: {complaint.get('status', '')}", f"Category: {complaint.get('category', '')}",
             f"Department: {complaint.get('department', '')}", f"Severity: {complaint.get('severity', '')}",
             "", "Track it at /track"]
    return "\n".join(lines)


def notify(user_ids, kind, message, complaint=None):
    """Notify each user in-app, plus email / SMS per their preferences. Returns the stored notifications."""
    users = {u["id"]: u for u in auth.load_users()}
    subject = f"[SCMS] {complaint['id'] + ': ' if complaint else ''}{SUBJECTS.get(kind, 'Update')}"
    now = datetime.now(timezone.utc).isoformat()
    records = []
    for uid in dict.fromkeys(user_ids):
        user = users.get(uid)
        if not user or not user.get("active", True):
            continue
        prefs = preferences(user)
        delivery = {"in_app": "delivered"}
        if prefs["email"]:
            delivery["email"] = _deliver(send_email, user["email"], subject, _email_body(message, complaint))
        if prefs["sms"] and prefs["phone"]:
            delivery["sms"] = _deliver(send_sms, prefs["phone"], f"SCMS: {message}")
        records.append({"id": "N-" + uuid.uuid4().hex[:10], "user_id": uid, "type": kind,
                        "complaint_id": complaint["id"] if complaint else None, "message": message,
                        "created_at": now, "read": False, "delivery": delivery})
    if records:
        with _lock:
            items = _load()
            items.extend(records)
            _save(items)
    return records


def supervisors():
    return [u["id"] for u in auth.load_users() if u["role"] == "supervisor" and u.get("active", True)]


def complaint_submitted(c):
    notify([c["citizen_id"]], "submitted", f"Your complaint {c['id']} ('{c['title']}') was received and is {c['status']}.", c)
    if c.get("assigned_to"):
        complaint_assigned(c)
    elif c.get("needs_supervisor"):
        notify(supervisors(), "needs_supervisor", f"Complaint {c['id']} has no available agent and needs assignment.", c)


def complaint_assigned(c):
    due = (c.get("sla") or {}).get("due_at", "")[:16].replace("T", " ")
    notify([c["assigned_to"]], "assigned",
           f"Complaint {c['id']} ('{c['title']}', {c['severity']} severity) is assigned to you"
           + (f", due {due} UTC." if due else "."), c)


def status_changed(c, actor_id, note=None):
    """Tell the citizen and the assigned agent (except whoever made the change)."""
    if c["status"] == "Resolved":
        kind = "resolution"
        message = (f"Complaint {c['id']} ('{c['title']}') has been resolved. "
                   "Please close it if fixed, or reopen it from the tracking page.")
    else:
        kind, message = "status_update", f"Complaint {c['id']} ('{c['title']}') is now {c['status']}."
    if note:
        message += f" Note: {note}"
    notify([u for u in (c.get("citizen_id"), c.get("assigned_to")) if u and u != actor_id], kind, message, c)


def sla_alerts(alerts, complaints):
    by_id = {c["id"]: c for c in complaints}
    for a in alerts:
        to = supervisors() if a["to"] == "supervisor" else [a["to"]]
        notify(to, f"sla_{a['type']}", a["message"], by_id.get(a["complaint_id"]))


# ---------- in-app inbox ----------
def for_user(user_id, unread_only=False):
    items = [n for n in _load() if n["user_id"] == user_id and not (unread_only and n["read"])]
    return sorted(items, key=lambda n: n["created_at"], reverse=True)


def mark_read(user_id, nid=None):
    """Mark one notification (or all, if nid is None) as read. Returns how many changed."""
    with _lock:
        items = _load()
        changed = 0
        for n in items:
            if n["user_id"] == user_id and not n["read"] and (nid is None or n["id"] == nid):
                n["read"] = True
                changed += 1
        if changed:
            _save(items)
    return changed
