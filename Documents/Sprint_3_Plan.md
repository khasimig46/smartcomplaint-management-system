# Sprint 3 Plan - Smart Complaint Management System

Sprint 3 (2-6 Nov) covers the spill-over found when the code was reviewed against the SRS, Use Case Flow, Architecture Justification and Test Plan in `Documents/`. Each task below uses the same format as the Sprint 1 and 2 GitHub issues (#1-#12) and can be pasted into a new issue. Each task is built on its own branch and merged by a PR that references the task.

| Task | Title | Priority | Status |
|---|---|---|---|
| 1 | Concurrency-Safe Storage & Unique Ticket IDs | High | In review |
| 2 | Resolution Rating, Feedback & Auto-Close | High | To do |
| 3 | Immutable Audit Log | High | To do |
| 4 | Admin User Management (CRUD) | High | To do |
| 5 | NLP Confidence Threshold (70%) | High | To do |
| 6 | SLA Rules per Category and Severity | Medium | To do |
| 7 | Citizen Reply to "Pending Info" | Medium | To do |
| 8 | Input Validation, Privacy & Workflow Fixes | High | To do |
| 9 | Asynchronous Notification Delivery | Medium | To do |
| 10 | Test Case Update & Test Reports | High | To do |

---

## Task 1. Concurrency-Safe Storage & Unique Ticket IDs

### Description
Fix a data-loss bug found in the Sprint 3 review. Every request reads a JSON file, changes it and writes it back without locking, and files are overwritten in place. When complaints are submitted at the same time, requests read the same list, generate the **same ticket ID** and overwrite each other's writes; some requests crash reading a half-written file.

Reproduced on `main`: 20 simultaneous submissions gave 6 crashes (`JSONDecodeError`), 14 responses that shared only **4** ticket IDs, and only **4** complaints saved.

### Features
- Atomic file writes
- Locked read-modify-write for every store
- Unique ticket IDs under concurrent load

### Tasks
- [ ] Create a shared storage module (`services/storage.py`) with atomic JSON writes (temp file + `os.replace`) and a shared lock
- [ ] Use it for the complaints, users, notifications and SLA-rules stores
- [ ] Hold the lock for the whole load -> generate ID -> save cycle in complaint submission
- [ ] Hold the lock in every other route that changes complaints (status, category override, notes, evidence, escalation, SLA monitor)
- [ ] Make user registration safe under concurrent requests
- [ ] Add concurrency tests

### Acceptance Criteria
- 20 simultaneous submissions return 20 unique ticket IDs and all 20 complaints are stored
- Concurrent registrations, notes and status changes lose no updates
- A failed write never leaves a partial or corrupt data file
- All existing tests still pass

### SRS / Docs Reference
FR-003 (Fail: duplicate ID), NFR-001 (500 concurrent users), Test Plan TC07

### Priority
High

---

## Task 2. Resolution Rating, Feedback & Auto-Close

### Description
FR-008 / UC-03 are not implemented: there is no way for a citizen to rate a resolution, and resolved complaints are never auto-closed. The dashboard already reads `rating`, but nothing writes it, so CSAT is always empty.

### Features
- 1-5 star rating with optional comment
- 7-day feedback window
- Auto-close of unrated complaints
- CSAT trend on the dashboard

### Tasks
- [ ] Create feedback module (rating 1-5, optional comment up to 500 characters)
- [ ] Add `POST /complaints/<id>/feedback` for the citizen who owns the complaint, only while it is Resolved
- [ ] Close the complaint when it is rated (UC-03 postcondition)
- [ ] Enforce the 7-day window, counted from the latest resolution (a reopened complaint gets a new window)
- [ ] Auto-close complaints left Resolved and unrated for 7 days from the SLA monitor job
- [ ] Add CSAT trend (average rating per day) to dashboard data and UI
- [ ] Resolution notification asks the citizen to rate within 7 days
- [ ] Add rating form and Close / Reopen buttons to the tracking page
- [ ] Add tests

### Acceptance Criteria
- Rating and comment are saved and the complaint is Closed
- Invalid ratings (0, 6, 4.5, text) are rejected
- Only the owner can rate, only once, only within 7 days
- Unrated complaints auto-close after 7 days, logged as done by the system
- Dashboard CSAT and CSAT trend update

### SRS / Docs Reference
FR-008, FR-011 (CSAT trends), US-03, UC-03, Test Plan TC14 / TC15, SRS ST-01

### Priority
High

---

## Task 3. Immutable Audit Log

### Description
FR-012 requires an immutable audit log of every complaint action with actor ID and timestamp, and UC-11 step 6 / UC-12 step 6 require logins and SLA alerts to be logged. Today only status changes are recorded (in the complaint's history); notes, evidence, overrides, escalations, logins and admin actions leave no trace.

### Features
- Append-only audit log
- Actor ID and timestamp on every entry
- Tamper detection
- Audit log viewer API

### Tasks
- [ ] Create audit module writing an append-only log (one JSON entry per line)
- [ ] Hash-chain the entries (each entry stores the previous entry's hash) so edits and deletions are detectable
- [ ] Record: submission, category override, status change, note, evidence, escalation, rating, auto-close, SLA alerts, SLA rule changes
- [ ] Record logins, failed logins (never the password), registrations and admin user changes
- [ ] Add `GET /audit` (supervisor / admin, filter by complaint or actor), `GET /complaints/<id>/audit` (staff), `GET /audit/verify` (admin)
- [ ] No update / delete endpoints
- [ ] Add tests

### Acceptance Criteria
- Every complaint action appears with actor ID and timestamp
- Full action history of a complaint is retrievable
- Editing or deleting a log line is reported by `/audit/verify`
- Citizens and agents cannot read the global log

### SRS / Docs Reference
FR-012, UC-11 step 6, UC-12 step 6, Architecture doc (append-only audit log), Test Plan TC19

### Priority
High

---

## Task 4. Admin User Management (CRUD)

### Description
FR-010 requires CRUD on user accounts, but only create and list exist. UC-09 step 5 (welcome email) is missing. There is no way to change a role or disable an account.

### Features
- View / edit / deactivate users
- Welcome email
- Safe deactivation

### Tasks
- [ ] Add `GET /auth/users/<id>`, `PATCH /auth/users/<id>` (name, email, role, department, zone, active), `DELETE /auth/users/<id>` (soft delete = deactivate)
- [ ] Validate role, department for agents, email format and uniqueness
- [ ] Stop an admin from deactivating or demoting their own account
- [ ] Send a welcome email when an admin creates an account (never include the password)
- [ ] When an agent is deactivated or moved, return their open complaints to the supervisor queue
- [ ] Add tests

### Acceptance Criteria
- Admin can read, update and deactivate accounts; other roles get 403
- Deactivated users cannot log in and their old tokens stop working
- New staff accounts receive a welcome email
- No open complaint is left assigned to a deactivated agent

### SRS / Docs Reference
FR-010, UC-09, SRS ST-03, Test Plan TC17

### Priority
High

---

## Task 5. NLP Confidence Threshold (70%)

### Description
FR-002 / US-07 require suggestions with at least 70% confidence, and UC-07 3a says that below 70% the citizen chooses the category manually. The current model **never** reaches 70%: the SRS example "water leakage from main pipe on 5th cross" scores 33% (the SRS test table records 87%). Cause: only 72 training rows (12 per category) and strong regularisation; 6-fold cross-validated accuracy is 61%. Submissions without a category silently use the top suggestion even when it is a guess.

### Features
- Better-trained model
- Confidence flag on suggestions
- Manual category choice when unsure

### Tasks
- [ ] Expand the training data (about 28 examples per category)
- [ ] Add character n-grams and reduce regularisation; report cross-validated accuracy
- [ ] Add `CONFIDENCE_THRESHOLD = 70` and a `confident` flag on each suggestion
- [ ] Reject a submission without a category when the top suggestion is below 70% and ask the citizen to choose
- [ ] Complaint form: do not pre-select a low-confidence suggestion, show a message instead
- [ ] Retrain automatically if the saved model file is missing, corrupt or from another scikit-learn version
- [ ] Add tests

### Acceptance Criteria
- The SRS example is classified as Water Supply with >= 70% confidence
- Clear complaints in every category are confident and correct
- Vague text is flagged low-confidence and the citizen must pick a category
- An unusable model file does not stop the service

### SRS / Docs Reference
FR-002, US-07, UC-07 3a, SRS IT-01, Test Plan TC05 / TC06

### Priority
High

---

## Task 6. SLA Rules per Category and Severity

### Description
FR-006 and US-10 say SLA deadlines are set per **category and severity**, and UC-10 lets the admin pick a category and severity. Today rules exist only per severity.

### Features
- Per-category SLA overrides
- Admin configuration
- Immediate effect on new complaints

### Tasks
- [ ] Extend SLA rules with `by_category: {category: {severity: hours}}` overrides on top of the severity defaults
- [ ] Validate category, severity and positive hours; allow removing an override
- [ ] Use the override when computing deadlines (submission and escalation)
- [ ] Update `PUT /sla/rules` (admin only)
- [ ] Add tests

### Acceptance Criteria
- A Critical Water Supply rule of 2 h applies to new Water Supply complaints only
- Invalid categories, severities or hours are rejected
- Changes apply to new complaints immediately

### SRS / Docs Reference
FR-006, US-10, UC-10

### Priority
Medium

---

## Task 7. Citizen Reply to "Pending Info"

### Description
FR-013 and UC-04 alternative flow 3a: the agent sets a complaint to Pending Info and queries the citizen, and the citizen replies. Agents can ask, but citizens have no way to answer, so the complaint stays stuck.

### Features
- Citizen reply
- Agent notification

### Tasks
- [ ] Add `POST /complaints/<id>/reply` for the owning citizen while the complaint is Pending Info
- [ ] Store the reply in the timeline and move the complaint back to In Progress
- [ ] Notify the assigned agent with the reply
- [ ] Add a reply box to the tracking page when the complaint is Pending Info
- [ ] Add tests

### Acceptance Criteria
- The citizen's reply appears in the timeline and the complaint returns to In Progress
- The agent is notified
- Only the owner can reply, only while Pending Info, with non-empty text

### SRS / Docs Reference
FR-013, UC-04 3a

### Priority
Medium

---

## Task 8. Input Validation, Privacy & Workflow Fixes

### Description
Defects found in the Sprint 3 review that break NFR-002 (OWASP) or the workflow rules:
- A JSON body that is a list / string / number, or a non-text field (e.g. `"title": 123`), causes a **500** on several endpoints
- Citizens can read internal data through `GET /complaints/<id>`: the escalation **reason**, previous agent and staff SLA alerts (the escalation notification hides the reason, but the API does not)
- Overriding the category to a department with no agent leaves the complaint **Assigned to nobody**; a supervisor can also set Assigned with no agent
- A citizen can change the category after work has started, so category and department no longer match
- `app.run(debug=True)` enables the Werkzeug debugger; there is no upload size limit

### Features
- Safe request parsing
- Citizen data redaction
- Consistent assignment state
- Production-safe config

### Tasks
- [ ] Add a JSON-body helper that rejects non-object bodies with 400; reject non-text fields with field errors
- [ ] Return JSON errors (400 / 404 / 405 / 413) instead of HTML pages
- [ ] Hide alerts and escalation reason / agents from the citizen view (keep 'Escalated' and the receiving team)
- [ ] When re-routing finds no agent: unassign, flag for the supervisor, go back to New if work had not started, notify supervisors
- [ ] Block 'Assigned' without an agent
- [ ] Citizens may change the category only before work starts
- [ ] Debug mode from an environment variable (off by default); set `MAX_CONTENT_LENGTH`
- [ ] Add tests

### Acceptance Criteria
- Malformed input returns 400 / 401, never 500
- Citizens never see escalation reasons or staff alerts
- No complaint is ever Assigned without an agent
- Debug is off by default and oversized requests get 413

### SRS / Docs Reference
NFR-002, FR-004, FR-005, FR-009, SRS ST-04

### Priority
High

---

## Task 9. Asynchronous Notification Delivery

### Description
The architecture document says notifications go through an asynchronous queue so a slow SMS / email provider never blocks submission, resolution or escalation. PR #22 sends email and SMS during the request with a 10 s timeout per message (noted there as a deviation).

### Features
- Background delivery queue
- Delivery status tracking

### Tasks
- [ ] Store the in-app notification immediately
- [ ] Queue email / SMS for a background worker; record `queued`, then `sent` / `failed`
- [ ] Keep an option to send inline (`NOTIFY_ASYNC=0`) for tests
- [ ] Add tests for both modes

### Acceptance Criteria
- Requests return without waiting for email / SMS providers
- Delivery status is updated after sending
- A provider failure is recorded as failed and never breaks a request

### SRS / Docs Reference
FR-007, Architecture justification (Reason 2), PR #22 deviation

### Priority
Medium

---

## Task 10. Test Case Update & Test Reports

### Description
Deliverables Part 3: update the test cases for the changes made in the sprints, run all testing per the Test Plan and upload the reports to the docs folder.

### Features
- Updated Test Case Document
- Unit Test Report
- System Validation Report
- Code Coverage Report
- Branch Coverage Report

### Tasks
- [ ] Update TC01-TC20 with actual results and the automated tests that cover them; add test cases for Sprint 3 work
- [ ] Add `.coveragerc` and run `pytest --cov --cov-branch`
- [ ] Write the Unit Test Report (per module: tests, pass / fail)
- [ ] Write the System Validation Report (each FR / NFR: validated, how, result; NFR-001 / 002 / 003 scope notes)
- [ ] Write the Code Coverage and Branch Coverage Reports (per file, with uncovered lines explained)
- [ ] Upload all reports to `Documents/`

### Acceptance Criteria
- Every SRS requirement maps to at least one test case with a recorded result
- All four reports are in the docs folder
- Coverage numbers match a CI run

### SRS / Docs Reference
Deliverables Part 3, Test Plan, SRS section 3

### Priority
High
