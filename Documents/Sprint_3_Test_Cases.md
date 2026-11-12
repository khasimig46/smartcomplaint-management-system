# Sprint 3 Test Cases – Smart Complaint Management System

Test cases follow the template in SRS section 3: Test Case ID, Name of Module, Test case description, Pre-conditions, Test Steps, Test data, Expected Results, Actual Result, Test Result. IDs continue the SRS numbering (UT-01 to UT-03, IT-01 to IT-03 and ST-01 to ST-04 are in the SRS). Test data is reused from the SRS test cases, and the expected results are the SRS acceptance criteria.

## Task 1 – Concurrency-Safe Storage & Unique Ticket IDs

Automated in `tests/test_storage.py`; each test function is named after its test case ID. "Simultaneous" means the requests are started together with a thread barrier.

| Test Case ID | Name of Module | Test case description | Pre-conditions | Test Steps | Test data | Expected Results | Actual Result | Test Result |
|---|---|---|---|---|---|---|---|---|
| UT-04 | Ticket ID Generation | To test that every complaint gets a unique ticket ID when complaints are submitted at the same time (FR-003) | Citizen is logged in; on home screen | 1: Open 'New Complaint' in 20 sessions<br>2: Enter the test data in each<br>3: Click Submit in all 20 sessions at the same time<br>4: Compare the ticket IDs on the 20 confirmations | Title: Pothole on MG Road<br>Description: Road surface damaged<br>Category: Roads<br>Severity: High<br>GPS: 12.9716, 77.5946<br>Submissions: 20 simultaneous | All 20 complaints are created; each confirmation shows a ticket ID in the SCMS-YYYYMMDD-NNNNN format; no ID is missing or duplicated | All 20 submissions succeeded with IDs SCMS-20261109-00001 to SCMS-20261109-00020; no duplicate or missing ID | Pass |
| UT-05 | Complaint Submission | To test that no complaint is lost and every field is saved when complaints are submitted at the same time (FR-001) | Citizen is logged in; on home screen | 1: Submit 20 complaints at the same time as in UT-04<br>2: Open each complaint by its ticket ID<br>3: Check the saved fields | Same as UT-04 | All 20 complaints are saved; each one shows title, description, category, severity and GPS location exactly as entered | All 20 complaints are stored and each opens with all fields as entered | Pass |
| UT-06 | User Management (RBAC) | To test that the admin can create several agent accounts at the same time without losing any (FR-010, UC-09) | Admin is logged in | 1: Navigate to User Management<br>2: Click 'Add User' for 20 agents<br>3: Click Save for all 20 at the same time<br>4: Log in as one of the new agents | Names: Agent 0 – Agent 19<br>Emails: agent0@scms.in – agent19@scms.in<br>Dept: Roads & Infrastructure<br>Role: Agent | All 20 accounts are created with role Agent; the new agent can log in with correct permissions | All 20 accounts created with role Agent; agent7@scms.in logged in as Agent | Pass |
| UT-07 | User Management (RBAC) | To test that the same email cannot create two accounts even when saved at the same time (UC-09 alternative flow 3a) | Admin is logged in | 1: Navigate to User Management<br>2: Click 'Add User' with the same details in 8 sessions<br>3: Click Save in all 8 at the same time<br>4: Check the user list | Name: Priya S<br>Email: priya@scms.in<br>Dept: Roads & Infrastructure<br>Role: Agent<br>Sessions: 8 simultaneous | Exactly one account is created; the other 7 attempts show the duplicate-account error | 1 account created; 7 attempts rejected with "An account with this email already exists"; priya@scms.in appears once | Pass |
| UT-08 | Add Notes and Evidence | To test that internal notes added at the same time are all saved with agent name and timestamp (FR-014, US-06) | Agent Ravi is logged in; a complaint is assigned to him | 1: Open the assigned complaint<br>2: Select 'Add Note' 20 times with different text<br>3: Save all 20 at the same time<br>4: Open the complaint's notes | Agent: Ravi (Water Dept – Zone 3)<br>Complaint: Water Supply, Zone 3<br>Notes: 'Field visit update 0' – 'Field visit update 19' | All 20 notes are saved, each with agent name Ravi and a timestamp, each with its own note ID | All 20 notes saved with author Ravi, a timestamp and 20 different IDs | Pass |
| IT-04 | Complaint Lifecycle / Add Notes | To test that a status change and notes made at the same moment are all recorded (FR-005, FR-014) | Agent Ravi is logged in; complaint is Assigned to him; citizen is logged in | 1: Agent changes status to 'In Progress'<br>2: At the same time, agent saves 9 notes<br>3: Citizen opens the complaint timeline<br>4: Agent opens the notes | Agent: Ravi<br>Status: In Progress<br>Notes: 'Checked valve 1' – 'Checked valve 9' | Status is In Progress; history shows New → Assigned → In Progress with timestamps (no transition skipped or unlogged); all 9 notes are saved | Status In Progress; history New → Assigned → In Progress, each with a timestamp; 9 notes saved | Pass |
| UT-09 | Data Reliability | To test that a failure while saving does not corrupt or lose complaints that were already saved (NFR-003, RPO) | Citizen is logged in; one complaint already saved | 1: Submit a complaint<br>2: Make the disk fail partway through saving (simulated)<br>3: Submit a second complaint<br>4: Open the first complaint | Complaint: as UT-04<br>Fault: "No space left on device" after a partial write | The second submission fails; the first complaint is still saved and opens normally; no half-saved complaint or temporary file is left | Second submission failed with "No space left on device"; first complaint opened normally; only one complaint stored; no temporary file left | Pass |

### Results before the fix (code on `main`, commit 66d1420)

The same automated tests were run against the code before Task 1, to show they detect the defect.

| Test Case ID | Result before fix | What happened |
|---|---|---|
| UT-04 | Fail | Simultaneous submissions crashed (a request read a half-written data file), so not every confirmation had a ticket ID. In a separate reproduction, 20 simultaneous submissions gave 14 confirmations that shared only 4 ticket IDs |
| UT-05 | Fail | Same crash; in the reproduction only 4 of the 20 complaints were stored |
| UT-06 | Fail | Only 1 of the 20 agent accounts remained in the user list |
| UT-07 | Fail | More than one attempt returned "created" for priya@scms.in, so the duplicate-account check was bypassed |
| UT-08 | Fail | Some note requests crashed instead of saving |
| IT-04 | Fail | Some of the simultaneous requests crashed instead of being recorded |
| UT-09 | Fail | Not a like-for-like run: the old code wrote the file in place (emptying it first) rather than through a temporary file, so the simulated fault never triggered. In place, a real failure part-way through would leave a truncated file |

### Traceability

| Requirement | SRS acceptance criterion checked | Test Case IDs |
|---|---|---|
| FR-001 | Pass: complaint saved with all fields | UT-05 |
| FR-003 | Pass: unique ID shown on confirmation. Fail: duplicate ID or missing | UT-04 |
| FR-005 | Fail: transition skipped or unlogged | IT-04 |
| FR-010 / UC-09 | Account created with correct role permissions; duplicate-account error (3a) | UT-06, UT-07 |
| FR-014 | Pass: note saved with agent name and timestamp | UT-08, IT-04 |
| NFR-003 | RPO: no loss of saved data | UT-09 |

NFR-001 (500 concurrent users, API p99 under 500 ms, page loads p95 under 2 s) needs a load-test environment and is not claimed by these test cases; it remains Test Plan TC20.
