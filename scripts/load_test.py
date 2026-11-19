"""TC20 / NFR-001: load test with 200 concurrent users against the app as it is run (`python app.py`).

NFR-001 originally asked for 500 concurrent users. The team revised it to 200 for this single-process,
JSON-file build (SRS 6.2): at 500 users with 1-5 s think time one Python process cannot keep API p99 under
500 ms. `--users 500` still runs the original target.

The server runs in its own process on a throw-away data folder, exactly as `python app.py` starts it
(Flask threaded server, SLA monitor, notification worker). The load generator runs in this process: each
virtual user is a thread that repeatedly does a weighted random action, then "thinks" for 1-5 s, like a
Locust user. Users start over a ramp-up period and then all run together for the measured period.

Login is measured separately: bcrypt (cost 12, ~0.3 s CPU by design) makes logins deliberately slow, and a
real user logs in once per 8-hour token, so the mix uses tokens issued at the start; a sample of users logs
in during the run and is reported as its own figure.

    python scripts/load_test.py                       # 200 users, 10 s ramp, 30 s steady
    python scripts/load_test.py --users 100 --duration 20 --out docs/reports/load-test.json
"""
import argparse
import json
import os
import random
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SECRET = "load-test-secret-key-0123456789abcdef"     # >= 32 bytes, only for this throw-away server
PASSWORD = "password123"
API_P99_MS, PAGE_P95_MS = 500, 2000
TARGET_USERS = 200                   # NFR-001 as revised (was 500)

TEXTS = [
    ("Water leakage", "water leakage from main pipe on 5th cross", "Water Supply"),
    ("Pothole", "big pothole on the main road near the school", "Roads"),
    ("Street light", "street light not working on our street at night", "Electricity"),
    ("Garbage", "garbage not collected for a week and it smells", "Sanitation"),
    ("Loud music", "loud music from a hall every night after midnight", "Noise Pollution"),
    ("Open manhole", "open manhole without cover is dangerous for children", "Public Safety"),
]


# ------------------------------------------------------------------ server side
def serve(data_dir, port):
    """Child process: the app as `python app.py` runs it, with its data files in data_dir."""
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("SECRET_KEY", SECRET)
    data = Path(data_dir)
    import routes.complaint_routes as cr
    import services.audit as audit
    import services.auth as auth
    import services.notifications as notifications
    import services.sla as sla
    cr.STORE, cr.UPLOADS = data / "complaints_store.json", data / "uploads"
    auth.USERS, sla.RULES_FILE = data / "users.json", data / "sla_rules.json"
    notifications.STORE, audit.LOG = data / "notifications.json", data / "audit_log.jsonl"
    from app import create_app
    from routes.sla_routes import start_monitor
    app = create_app()
    start_monitor(app)
    notifications.start_delivery_worker()
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)


def seed(data_dir, users):
    """Write the user accounts directly (one bcrypt hash shared by all) and return the citizens."""
    import bcrypt
    from services.routing import DEPARTMENTS, DEFAULT_DEPARTMENT
    pw = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()
    now = datetime.now(timezone.utc).isoformat()

    def user(role, i, department=None):
        return {"id": "U-" + uuid.uuid4().hex[:8], "name": f"{role} {i}", "email": f"{role}{i}@load.test",
                "password_hash": pw, "role": role, "department": department, "zone": None, "active": True,
                "created_at": now, "auth_version": 0}
    staff = [user("supervisor", 0)] + [user("agent", i, d) for i, d in
                                       enumerate([*DEPARTMENTS.values(), DEFAULT_DEPARTMENT] * 2)]
    citizens = [user("citizen", i) for i in range(users)]
    Path(data_dir, "users.json").write_text(json.dumps(staff + citizens))
    return citizens, staff[0]


def token(u):
    import jwt
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": u["id"], "role": u["role"], "ver": 0, "iat": now, "exp": now + timedelta(hours=8)},
                      SECRET, algorithm="HS256")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ client side
class Recorder:
    def __init__(self):
        self.lock, self.samples, self.errors = threading.Lock(), [], []

    def add(self, kind, name, ms, ok, detail=""):
        with self.lock:
            self.samples.append((kind, name, ms, ok))
            if not ok:
                self.errors.append(f"{name}: {detail}")


def call(base, rec, kind, name, method, path, tok=None, body=None, expect=(200, 201)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        payload, status = e.read(), e.code
    except Exception as e:                                  # refused / reset / timeout
        rec.add(kind, name, (time.perf_counter() - start) * 1000, False, repr(e))
        return None
    ms = (time.perf_counter() - start) * 1000
    rec.add(kind, name, ms, status in expect, f"HTTP {status}")
    return payload if status in expect else None


def virtual_user(base, rec, citizen, tok, stop, measuring, rng):
    mine = []
    actions = [("suggest", 20), ("submit", 10), ("mine", 25), ("view", 15), ("inbox", 15), ("page", 15)]
    names, weights = zip(*actions)
    while not stop.is_set():
        action = rng.choices(names, weights)[0]
        kind = "page" if action == "page" else "api"
        r = rec if measuring.is_set() else Recorder()        # ramp-up traffic is not measured
        title, text, category = rng.choice(TEXTS)
        if action == "suggest":
            call(base, r, kind, "POST /suggest-category", "POST", "/suggest-category", body={"text": text})
        elif action == "submit":
            out = call(base, r, kind, "POST /submit-complaint", "POST", "/submit-complaint", tok,
                       {"title": title, "description": text, "severity": rng.choice(["Low", "Medium", "High"]),
                        "category": category})
            if out:
                mine.append(json.loads(out)["id"])
        elif action == "mine" or (action == "view" and not mine):
            call(base, r, kind, "GET /complaints/mine", "GET", "/complaints/mine", tok)
        elif action == "view":
            call(base, r, kind, "GET /complaints/<id>", "GET", f"/complaints/{rng.choice(mine)}", tok)
        elif action == "inbox":
            call(base, r, kind, "GET /notifications/data", "GET", "/notifications/data", tok)
        else:
            page = rng.choice(["/", "/track", "/login", "/notifications"])
            call(base, r, "page", f"GET {page} (page)", "GET", page)
        stop.wait(rng.uniform(1, 5))


def supervisor_user(base, rec, tok, stop, measuring, rng):
    while not stop.is_set():
        r = rec if measuring.is_set() else Recorder()
        call(base, r, "api", "GET /dashboard/data", "GET", "/dashboard/data", tok)
        stop.wait(rng.uniform(5, 10))


def login_sampler(base, rec, citizens, stop, measuring, rng):
    while not stop.is_set():
        if measuring.is_set():
            call(base, rec, "login", "POST /auth/login", "POST", "/auth/login",
                 body={"email": rng.choice(citizens)["email"], "password": PASSWORD})
        stop.wait(rng.uniform(1, 2))


def pct(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * len(values) + 0.5)) - 1)]


def run(users=TARGET_USERS, ramp=10, duration=30, seed_value=2026):
    rng = random.Random(seed_value)
    data_dir = tempfile.mkdtemp(prefix="scms-load-")
    citizens, supervisor = seed(data_dir, users)
    port = free_port()
    env = {**os.environ, "SECRET_KEY": SECRET, "PYTHONPATH": str(ROOT)}
    log_path = Path(data_dir) / "server.log"              # a file, not a pipe: an unread pipe fills and blocks
    log_file = open(log_path, "w")
    server = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", data_dir, str(port)],
                              cwd=ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(300):                                   # wait for the server (model loads first)
            try:
                urllib.request.urlopen(base + "/categories", timeout=2).read()
                break
            except Exception:
                if server.poll() is not None:
                    raise RuntimeError("server exited: " + log_path.read_text()[-2000:])
                time.sleep(0.2)
        rec, stop, measuring = Recorder(), threading.Event(), threading.Event()
        threads = [threading.Thread(target=supervisor_user, args=(base, rec, token(supervisor), stop, measuring,
                                                                  random.Random(rng.random())), daemon=True),
                   threading.Thread(target=login_sampler, args=(base, rec, citizens, stop, measuring,
                                                                random.Random(rng.random())), daemon=True)]
        for t in threads:
            t.start()
        for i, c in enumerate(citizens):                       # ramp-up: start users evenly over `ramp` seconds
            t = threading.Thread(target=virtual_user, args=(base, rec, c, token(c), stop, measuring,
                                                            random.Random(rng.random())), daemon=True)
            t.start()
            threads.append(t)
            time.sleep(ramp / users)
        measuring.set()
        started = time.perf_counter()
        time.sleep(duration)
        measuring.clear()
        elapsed = time.perf_counter() - started
        stop.set()
        for t in threads:
            t.join(timeout=35)
    finally:
        server.terminate()
        server.wait(timeout=10)
        log_file.close()

    def summary(rows):
        ms = [s[2] for s in rows]
        return {"requests": len(rows), "errors": sum(1 for s in rows if not s[3]),
                "median_ms": round(statistics.median(ms), 1) if ms else 0,
                "p95_ms": round(pct(ms, 95), 1), "p99_ms": round(pct(ms, 99), 1), "max_ms": round(max(ms, default=0), 1)}
    api = [s for s in rec.samples if s[0] == "api"]
    pages = [s for s in rec.samples if s[0] == "page"]
    logins = [s for s in rec.samples if s[0] == "login"]
    endpoints = {n: summary([s for s in rec.samples if s[1] == n]) for n in sorted({s[1] for s in rec.samples})}
    result = {
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "users": users, "ramp_s": ramp, "measured_s": round(elapsed, 1), "think_time_s": [1, 5],
        "throughput_rps": round(len(rec.samples) / elapsed, 1),
        "api": summary(api), "pages": summary(pages), "login": summary(logins), "endpoints": endpoints,
        "targets": {"api_p99_ms": API_P99_MS, "page_p95_ms": PAGE_P95_MS},
        "first_errors": rec.errors[:10],
        "server_log": str(log_path),
    }
    result["passed"] = (result["api"]["p99_ms"] < API_P99_MS and result["pages"]["p95_ms"] < PAGE_P95_MS
                        and result["api"]["errors"] == 0 and result["pages"]["errors"] == 0)
    return result


def describe(r):
    return (f"TC20 load test: {r['users']} users, {r['api']['requests'] + r['pages']['requests']} requests in "
            f"{r['measured_s']} s, errors {r['api']['errors'] + r['pages']['errors']}, API p99 {r['api']['p99_ms']} ms, "
            f"page p95 {r['pages']['p95_ms']} ms, login p99 {r['login']['p99_ms']} ms")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--serve":
        serve(sys.argv[2], int(sys.argv[3]))
        sys.exit(0)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--users", type=int, default=TARGET_USERS)
    ap.add_argument("--ramp", type=float, default=10)
    ap.add_argument("--duration", type=float, default=30)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    res = run(a.users, a.ramp, a.duration)
    print(json.dumps(res, indent=2))
    print(describe(res))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(res, indent=2))
    sys.exit(0 if res["passed"] else 1)
