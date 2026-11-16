# Smart Complaint Management System (SCMS)

Software Engineering mini-project, PES University, Team 5D: Kanchhit kumar (`finnajumpoff`), `khasimig46`, Krishh Aryan (`krrisharyan28`).

Citizens report civic problems (water, roads, electricity, sanitation, noise, public safety). The system suggests a category, routes each complaint to the right department and the least-loaded agent, tracks SLA deadlines, escalates stalled work, collects ratings, and keeps a tamper-evident audit log.

## Quick start

Needs Python 3.11 or newer.

```bash
git clone https://github.com/khasimig46/smartcomplaint-management-system.git
cd smartcomplaint-management-system
python -m venv venv
venv\Scripts\activate            # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
python -m nlp.train_model        # retrains the category model for your scikit-learn version
python scripts/seed_demo.py      # demo accounts + 8 complaints (see below)
python app.py                    # http://127.0.0.1:5000
```

Use `python app.py`, not `flask run`: only `python app.py` starts the SLA monitor, which sends deadline alerts and auto-closes unrated complaints every 60 seconds.

To start over: `python scripts/seed_demo.py --reset`. This **deletes all local data** (complaints, users, notifications, SLA rules, audit log, uploads).

## Demo accounts

Every account's password is `Demo@2026`.

| Role | Email | Department |
|---|---|---|
| Admin | admin@demo.local | |
| Supervisor | supervisor@demo.local | |
| Agent | water.agent@demo.local, water.agent2@demo.local | Water Department (zones North / South) |
| Agent | roads.agent@demo.local | Roads & Infrastructure |
| Agent | power.agent@demo.local | Electricity Department |
| Agent | sanitation.agent@demo.local | Sanitation Department |
| Agent | environment.agent@demo.local | Environment Department |
| Agent | safety.agent@demo.local | Public Safety Department |
| Agent | general.agent@demo.local | General Administration |
| Citizen | asha@demo.local, vikram@demo.local | |

Seeded complaints, one per demo scenario:

| # | Status | What to show |
|---|---|---|
| 1 | Assigned | Fresh complaint, routed to the North-zone water agent |
| 2 | In Progress | Agent's internal note (hidden from the citizen) |
| 3 | Pending Info | Vikram answers the agent's question → back to In Progress |
| 4 | Resolved | Asha rates it → Closed, dashboard CSAT changes |
| 5 | Closed | Rated 4/5: feeds the CSAT trend |
| 6 | In Progress, overdue | SLA breach alert; top of the supervisor's escalation list |
| 7 | Closed | Auto-closed by the system after 7 days without a rating |
| 8 | In Progress, idle 72 h | Shows up as stalled; escalate it live |

Some seeded times are moved into the past so these states exist. That changes the complaint records only: the audit log shows when each action was actually seeded, and the ticket IDs carry today's date.

## Pages

| Page | URL | Who |
|---|---|---|
| Log in / register | `/login` | everyone |
| New complaint | `/` | citizen |
| Track complaint (timeline, reply, rate, close/reopen) | `/track` | citizen, staff |
| Work queue | `/agent` | agent |
| Escalations | `/escalations` | supervisor, admin |
| Dashboard and CSV report | `/dashboard` | supervisor, admin |
| Notifications and preferences | `/notifications` | everyone |
| SLA rules | `/sla/admin` | admin |
| Audit log and integrity check | `/audit/view` | supervisor, admin |

## Configuration

Set these as environment variables. All are optional for a local demo.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs login tokens. **Set it for anything beyond a local demo**: without it the app uses a public development key. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Creates the first admin on start-up (the seed script sets them to the demo admin if unset) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS` | Email notifications; skipped when `SMTP_HOST` is unset |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` | SMS notifications for users who opt in |

## Tests and reports

```bash
pytest                                   # whole suite, about 4 minutes
pytest --cov --cov-branch                # with statement + branch coverage
python scripts/generate_reports.py       # rebuilds the Part-3 PDFs in docs/ (runs the suite)
```

CI runs the suite on every push and pull request (`.github/workflows/ci.yml`).

## Documents

- `Documents/`: SRS, Test Plan and SAD (v2.0, in the course templates), use-case flows, UML diagram sources in `Documents/diagrams/`; v1.0 versions in `Documents/v1/`
- `docs/`: unit test, system validation, code coverage and branch coverage reports, and the updated test case document

## Known limitations

These are documented in the SAD (section 3.5, ADRs, and section 4.6):

- Data lives in JSON files guarded by an in-process lock: **run one process only**. Several workers (e.g. `gunicorn -w 4`) would lose writes.
- Email/SMS are sent inside the request; a slow provider slows the request down.
- No rate limiting on login or submission.
- The 70% NLP confidence threshold, admin user update/deactivate, and asynchronous notifications are open Sprint 3 tasks.
- Not load-tested for 500 concurrent users; no TLS (the hosting platform must provide it).
