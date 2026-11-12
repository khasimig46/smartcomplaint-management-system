"""Run the full test suite once and generate the Part-3 test reports into docs/.

Usage (from the repo root):
    pip install -r requirements.txt
    python -m nlp.train_model          # only needed once
    python scripts/generate_reports.py

Writes:
    docs/Unit_Test_Report.pdf
    docs/System_Validation_Report.pdf
    docs/Code_Coverage_Report.pdf
    docs/Branch_Coverage_Report.pdf
    docs/Test_Cases_Updated.pdf
    docs/reports/  (raw evidence: JUnit XML, pytest HTML report, coverage JSON/XML and HTML site)
"""
import json
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cases import CASES, SV_CASES  # noqa: E402

DOCS, RAW = ROOT / "docs", ROOT / "docs" / "reports"
PROJECT = "Smart Complaint Management System"
TEAM = "Team 5D"

# ---------------------------------------------------------------- run
def run_suite():
    RAW.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-rA",
           f"--junitxml={RAW / 'junit.xml'}", f"--html={RAW / 'unit-test-report.html'}", "--self-contained-html",
           "--cov", "--cov-branch", f"--cov-report=json:{RAW / 'coverage.json'}",
           f"--cov-report=xml:{RAW / 'coverage.xml'}", f"--cov-report=html:{RAW / 'coverage-html'}"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    (RAW / "pytest-output.txt").write_text(out.stdout + out.stderr)
    m = re.search(r"SV-10 latency over (\d+) requests: median ([\d.]+) ms, p99 ([\d.]+) ms", out.stdout)
    return out.returncode, (m.groups() if m else None)


def load_junit():
    tests = OrderedDict()
    for tc in ET.parse(RAW / "junit.xml").getroot().iter("testcase"):
        mod = tc.get("classname").replace(".", "/") + ".py"
        outcome, msg = "Pass", ""
        for tag in ("failure", "error"):
            el = tc.find(tag)
            if el is not None:
                outcome, msg = "Fail", (el.get("message") or "")[:300]
        if tc.find("skipped") is not None:
            outcome = "Skipped"
        tests[f"{mod}::{tc.get('name')}"] = dict(module=mod, name=tc.get("name"), time=float(tc.get("time", 0)),
                                                  outcome=outcome, message=msg)
    return tests


def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""

# ---------------------------------------------------------------- pdf helpers
for name, file in (("Carlito", "Carlito-Regular.ttf"), ("Carlito-Bold", "Carlito-Bold.ttf")):
    try:
        pdfmetrics.registerFont(TTFont(name, f"/usr/share/fonts/truetype/crosextra/{file}"))
        FONT, BOLD = "Carlito", "Carlito-Bold"
    except Exception:
        FONT, BOLD = "Helvetica", "Helvetica-Bold"

INK, GREY, LINE = colors.HexColor("#111111"), colors.HexColor("#555555"), colors.HexColor("#999999")
HEAD_BG = colors.HexColor("#E6E6E6")
STATUS_BG = {"Pass": colors.HexColor("#DFF0D8"), "Fail": colors.HexColor("#F2DEDE"),
             "Partial": colors.HexColor("#FCF8E3"), "Not Implemented": colors.HexColor("#F2DEDE"),
             "Not Executed": colors.HexColor("#EEEEEE"), "Open": colors.HexColor("#F2DEDE"),
             "Fixed on branch": colors.HexColor("#FCF8E3"), "Deviation": colors.HexColor("#FCF8E3")}

ST = {
    "title": ParagraphStyle("t", fontName=BOLD, fontSize=20, leading=24, alignment=TA_CENTER, textColor=INK),
    "sub": ParagraphStyle("s", fontName=FONT, fontSize=11, leading=14, alignment=TA_CENTER, textColor=GREY),
    "h1": ParagraphStyle("h1", fontName=BOLD, fontSize=14, leading=18, spaceBefore=10, spaceAfter=4, textColor=INK),
    "h2": ParagraphStyle("h2", fontName=BOLD, fontSize=11.5, leading=15, spaceBefore=6, spaceAfter=3, textColor=INK),
    "body": ParagraphStyle("b", fontName=FONT, fontSize=10, leading=13.5, spaceAfter=4, textColor=INK),
    "cell": ParagraphStyle("c", fontName=FONT, fontSize=8, leading=10, textColor=INK),
    "cellb": ParagraphStyle("cb", fontName=BOLD, fontSize=8, leading=10, textColor=INK),
    "small": ParagraphStyle("sm", fontName=FONT, fontSize=8.5, leading=11, textColor=GREY),
}


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def P(text, style="body"):
    return Paragraph(text, ST[style])


def table(rows, widths, status_col=None, head=True, zebra=False):
    data = [[c if not isinstance(c, str) else P(esc(c).replace("\n", "<br/>"), "cellb" if head and i == 0 else "cell")
             for c in row] for i, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
             ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    if head:
        style.append(("BACKGROUND", (0, 0), (-1, 0), HEAD_BG))
    if status_col is not None:
        for r, row in enumerate(rows[1:], 1):
            bg = STATUS_BG.get(row[status_col])
            if bg:
                style.append(("BACKGROUND", (status_col, r), (status_col, r), bg))
    t.setStyle(TableStyle(style))
    return t


def meta_table(meta, width):
    return table([[k, v] for k, v in meta], [width * 0.28, width * 0.72], head=False)


def build(path, title, subtitle, meta, story, landscape_mode=False):
    size = landscape(A4) if landscape_mode else A4
    doc = SimpleDocTemplate(str(path), pagesize=size, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm, title=title, author=TEAM, subject=PROJECT)
    width = size[0] - 30 * mm

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.setFillColor(GREY)
        canvas.drawString(15 * mm, 8 * mm, f"{PROJECT} - {title}")
        canvas.drawRightString(size[0] - 15 * mm, 8 * mm, f"Page {d.page}")
        canvas.restoreState()

    head = [P(title, "title"), Spacer(1, 3), P(f"{PROJECT} &middot; {TEAM}", "sub"), P(subtitle, "sub"),
            Spacer(1, 8), meta_table(meta, width), Spacer(1, 6)]
    doc.build(head + story(width), onFirstPage=footer, onLaterPages=footer)

# ---------------------------------------------------------------- reports
def case_status(case, junit):
    if case.get("fixed_status"):
        return case["fixed_status"], []
    runs = {t: [k for k in junit if k == t or k.startswith(t + "[")] for t in case["tests"]}
    missing = [t for t, ks in runs.items() if not ks]
    if missing:
        raise SystemExit(f"{case['id']}: tests not found in the run: {missing}")
    failed = [t for t, ks in runs.items() if any(junit[k]["outcome"] != "Pass" for k in ks)]
    return ("Fail" if failed else "Pass"), failed


def short(nodeid):
    mod, name = nodeid.split("::")
    return f"{Path(mod).stem}::{name}"


def unit_report(junit, meta):
    unit = {k: v for k, v in junit.items() if "test_system_validation" not in k}
    by_mod = OrderedDict()
    for t in unit.values():
        by_mod.setdefault(t["module"], []).append(t)
    total = len(unit)
    passed = sum(t["outcome"] == "Pass" for t in unit.values())
    secs = sum(t["time"] for t in unit.values())

    def story(w):
        s = [P("1. Summary", "h1"),
             P(f"<b>{passed} of {total}</b> unit/module tests passed ({100 * passed / total:.1f}%), "
               f"{total - passed} failed, 0 skipped. Total execution time {secs:.1f} s. Tests are written with "
               "pytest and run in isolation: every test gets a fresh temporary data directory, and email/SMS "
               "providers are replaced by an in-memory outbox, so no test depends on another or on the network."),
             P("2. Scope and approach", "h1"),
             P("These are the module-level tests for each feature built in Sprints 1 and 2 (one test file per GitHub "
               "issue). They call the service functions directly, or a single API endpoint through Flask's test "
               "client, and check one behaviour each. End-to-end flows across modules are reported separately in "
               "the System Validation Report. The suite also runs automatically in GitHub Actions on every push and "
               "pull request (.github/workflows/ci.yml)."),
             P("3. Results by module", "h1")]
        rows = [["Module (test file)", "Feature / issue", "Tests", "Passed", "Failed", "Time (s)"]]
        feat = {"test_auth": "#1 Auth & roles", "test_submission": "#2 Complaint submission",
                "test_categorizer": "#3 AI categorisation", "test_ticket_id": "#4 Ticket ID",
                "test_routing": "#5 Smart routing", "test_status": "#6 Status tracking",
                "test_resolution": "#7 Agent resolution", "test_evidence": "#8 Evidence upload",
                "test_sla": "#9 SLA monitoring", "test_escalation": "#10 Escalation",
                "test_notifications": "#11 Notifications", "test_dashboard": "#12 Dashboard"}
        for mod, ts in by_mod.items():
            p = sum(t["outcome"] == "Pass" for t in ts)
            rows.append([mod, feat.get(Path(mod).stem, ""), str(len(ts)), str(p), str(len(ts) - p),
                         f"{sum(t['time'] for t in ts):.2f}"])
        rows.append(["Total", "", str(total), str(passed), str(total - passed), f"{secs:.2f}"])
        s.append(table(rows, [w * .3, w * .28, w * .1, w * .1, w * .1, w * .12]))
        s += [P("4. Test-by-test results", "h1")]
        rows = [["#", "Test", "Result", "Time (s)"]]
        for i, t in enumerate(unit.values(), 1):
            rows.append([str(i), f"{Path(t['module']).stem}::{t['name']}", t["outcome"], f"{t['time']:.3f}"])
        s.append(table(rows, [w * .06, w * .7, w * .12, w * .12], status_col=2))
        fails = [t for t in unit.values() if t["outcome"] != "Pass"]
        s += [P("5. Failures", "h1"), P("None." if not fails else "")]
        for t in fails:
            s.append(P(f"<b>{esc(t['name'])}</b>: {esc(t['message'])}", "small"))
        s += [P("6. Evidence", "h1"),
              P("Raw results are in docs/reports/: junit.xml (machine-readable), unit-test-report.html (pytest-html, "
                "open in a browser) and pytest-output.txt (console log). Regenerate with "
                "<font face='Courier'>python scripts/generate_reports.py</font>.")]
        return s
    build(DOCS / "Unit_Test_Report.pdf", "Unit Test Report", "Software Engineering Mini-Project - Part 3", meta, story)
    return passed, total


def coverage_reports(cov, meta):
    files = OrderedDict(sorted(cov["files"].items()))
    tot = cov["totals"]

    def stmt_story(w):
        s = [P("1. Summary", "h1"),
             P(f"Statement coverage across the application code is <b>{tot['percent_statements_covered']:.1f}%</b> "
               f"({tot['covered_lines']} of {tot['num_statements']} statements executed). The figure combines all "
               f"{meta_count} automated tests (unit and system). Measured with coverage.py through pytest-cov; test "
               "files and scripts are excluded (.coveragerc), so the number reflects only product code."),
             P("2. Coverage by file", "h1")]
        rows = [["File", "Statements", "Missed", "Covered %", "Missing lines"]]
        for f, d in files.items():
            sm = d["summary"]
            rows.append([f, str(sm["num_statements"]), str(sm["missing_lines"]),
                         f"{sm['percent_statements_covered']:.1f}", compress(d["missing_lines"]) or "-"])
        rows.append(["TOTAL", str(tot["num_statements"]), str(tot["missing_lines"]),
                     f"{tot['percent_statements_covered']:.1f}", ""])
        s.append(table(rows, [w * .3, w * .12, w * .1, w * .12, w * .36]))
        s += [P("3. Analysis of uncovered code", "h1")] + [P(f"&bull; {x}") for x in STMT_NOTES]
        s += [P("4. Limitations of this metric", "h1"),
              P("Statement coverage shows which lines ran, not whether their results were checked; it is backed here "
                "by assertions in every test. It cannot show missing features (TC06, TC14, TC15, TC19 are not "
                "implemented, so there is no code to cover), and it says nothing about the templates and JavaScript, "
                "which are exercised only in manual browser testing. Branch coverage, in the companion report, is "
                "the stricter measure."),
              P("5. Evidence", "h1"),
              P("docs/reports/coverage-html/index.html (browse line by line), coverage.json and coverage.xml "
                "(Cobertura format).")]
        return s

    def branch_story(w):
        s = [P("1. Summary", "h1"),
             P(f"Branch coverage is <b>{100 * tot['covered_branches'] / tot['num_branches']:.1f}%</b>: "
               f"{tot['covered_branches']} of {tot['num_branches']} branch outcomes were taken. "
               f"{tot['num_partial_branches']} decision points were only partly exercised (one outcome taken, "
               f"the other not). The combined statement+branch figure reported by coverage.py is "
               f"<b>{tot['percent_covered']:.1f}%</b>."),
             P("Branch coverage counts each possible outcome of every <i>if</i>, loop and conditional expression. "
               "A line can be 100% statement-covered while one of its outcomes is never tested, which is why this "
               "report is kept separate from the statement coverage report."),
             P("2. Branch coverage by file", "h1")]
        rows = [["File", "Branches", "Taken", "Partial", "Branch %", "Missed arcs (line -> target)"]]
        for f, d in files.items():
            sm = d["summary"]
            if not sm["num_branches"]:
                continue
            arcs = ", ".join(f"{a}->{'exit' if b < 0 else b}" for a, b in d.get("missing_branches", [])) or "-"
            rows.append([f, str(sm["num_branches"]), str(sm["covered_branches"]), str(sm["num_partial_branches"]),
                         f"{100 * sm['covered_branches'] / sm['num_branches']:.1f}", arcs])
        rows.append(["TOTAL", str(tot["num_branches"]), str(tot["covered_branches"]),
                     str(tot["num_partial_branches"]), f"{100 * tot['covered_branches'] / tot['num_branches']:.1f}", ""])
        s.append(table(rows, [w * .27, w * .1, w * .09, w * .09, w * .1, w * .35]))
        s += [P("Files with no decision points (for example routes/dashboard_routes.py) are omitted from the table "
                "and are fully covered.", "small"),
              P("3. Analysis of untaken branches", "h1")] + [P(f"&bull; {x}") for x in BRANCH_NOTES]
        s += [P("4. Limitations", "h1"),
              P("Branch coverage does not show combinations of conditions (MC/DC) or concurrency. For example, every "
                "branch of the submission handler is covered, yet concurrent submissions on main still corrupt the "
                "data file (defect DEF-01 in the System Validation Report). Branch coverage is a floor, not proof of "
                "correctness."),
              P("5. Evidence", "h1"),
              P("docs/reports/coverage-html/index.html marks partial branches in yellow; coverage.xml carries the "
                "branch-rate per file.")]
        return s

    meta_count = len(load_junit())
    build(DOCS / "Code_Coverage_Report.pdf", "Code Coverage Report", "Statement coverage - Part 3", meta, stmt_story)
    build(DOCS / "Branch_Coverage_Report.pdf", "Branch Coverage Report", "Decision (branch) coverage - Part 3",
          meta, branch_story)


def compress(lines):
    out, start, prev = [], None, None
    for n in lines:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(out)


STMT_NOTES = [
    "<b>nlp/train_model.py</b> (lowest, about 57%): the training routine and its <i>__main__</i> block. CI trains "
    "the model once (python -m nlp.train_model) before the tests, and inside the run the saved model is loaded. "
    "Model quality is checked by test_categorizer instead of retraining in every test.",
    "<b>app.py</b>: the HTML page routes (/, /track, /login) and the <i>__main__</i> block that starts the server "
    "and the SLA thread. These are exercised in manual browser testing, not by pytest.",
    "<b>routes/sla_routes.py</b>: GET /sla/rules, the agent-only filter in /sla/alerts, and the 60-second "
    "background monitor (start_monitor). The monitor's work, run_check, is covered through POST /sla/check.",
    "<b>routes/complaint_routes.py</b>: GET /categories, and the error exits of category override (invalid "
    "category, no permission, unknown complaint) and of GET / PATCH on an unknown complaint ID.",
    "<b>services/auth.py</b>: create_user validation messages for an empty name, an unknown role and an agent with "
    "no department; a token for an account that was deleted or deactivated; seeding the first admin from "
    "ADMIN_EMAIL / ADMIN_PASSWORD.",
    "<b>Remaining single lines</b> are similar error exits: 404/403 on listing notes and evidence, an unknown status "
    "name, the real SMTP login, and the ticket-ID guards for more than 99,999 tickets a day or a duplicate.",
    "The gaps are start-up code and rare error paths. Every requirement that is implemented has its main path "
    "covered.",
]
BRANCH_NOTES = [
    "<b>routes/complaint_routes.py</b> (9 missed arcs): the lookup loops never fall through to 'not found' in tests, "
    "and category override is never tried on a complaint whose work has started (status past Assigned), so the "
    "'do not re-route' outcome (line 112 -> 116) is untested.",
    "<b>services/auth.py</b> (6): the false outcomes of create_user's validation checks listed above, find_user "
    "returning nothing, and the disabled-account check on a valid token.",
    "<b>routes/evidence_routes.py</b> and <b>routes/resolution_routes.py</b>: 404 and 403 outcomes when listing or "
    "downloading notes and evidence.",
    "<b>routes/sla_routes.py</b>: the background monitor loop is never entered, and /sla/alerts is never called by "
    "an agent.",
    "<b>services/ticket_id.py</b>: the daily-limit and duplicate guards are defensive and never true in normal use.",
    "<b>services/notifications.py</b>: SMTP with TLS turned off and SMTP login with a username are not reached, "
    "because tests replace the providers with an in-memory outbox.",
    "Suggested Sprint 3 additions: not-found and forbidden tests for each complaint endpoint, an override after "
    "work has started, create_user validation tests, and a token for a deactivated account. These cover most of the "
    "remaining partial branches without changing product code.",
]


def system_report(junit, meta, latency):
    def sv_status(fn):
        return junit[f"tests/test_system_validation.py::{fn}"]["outcome"]
    rbac = [k for k in junit if "test_sv06_rbac_matrix" in k]
    statuses = {c["id"]: case_status(c, junit)[0] for c in CASES}

    def story(w):
        sv_pass = sum(sv_status(fn) == "Pass" for _, fn, *_ in SV_CASES if not fn.startswith("test_sv06")) \
                  + all(junit[k]["outcome"] == "Pass" for k in rbac)
        s = [P("1. Purpose", "h1"),
             P("This report validates the integrated system against the SRS. It records the end-to-end system "
               "validation runs (SV-01 to SV-10), the resulting status of every requirement, the defects found and "
               "the deviations from the original SRS/SAD that the team will explain at the demo."),
             P("2. Environment", "h1"),
             P(f"Application commit {meta_commit}, Python {platform.python_version()} on {platform.system()}, "
               "Flask test client (in-process HTTP), JSON file storage in a fresh temporary directory per test, "
               "email/SMS providers stubbed. The same suite runs in GitHub Actions on ubuntu-latest / Python 3.11."),
             P("3. System validation runs", "h1"),
             P(f"<b>{sv_pass} of {len(SV_CASES)}</b> system validation cases passed (SV-06 runs as {len(rbac)} "
               "parameterised sub-tests, one per protected endpoint).")]
        rows = [["ID", "Flow validated", "Test cases", "Requirements", "Result"]]
        for sid, fn, flow, tcs, reqs in SV_CASES:
            res = ("Pass" if all(junit[k]["outcome"] == "Pass" for k in rbac) else "Fail") if "sv06" in fn \
                else sv_status(fn)
            rows.append([sid, flow, tcs, reqs, res])
        s.append(table(rows, [w * .07, w * .45, w * .18, w * .18, w * .12], status_col=4))
        s.append(P("* TC06: SV-03 confirms only the manual-selection fallback, not the 70% threshold.", "small"))
        if latency:
            n, med, p99 = latency
            s.append(P(f"SV-10 measured {n} requests: median {med} ms, p99 {p99} ms (single client, in-process, no "
                       "network). This shows the application code is far inside the 500 ms budget, but it is "
                       "<b>not</b> the 500-concurrent-user test NFR-001 requires; see DEF-01 for why concurrency "
                       "must be fixed first."))
        s += [P("4. Requirement validation matrix", "h1")]
        req_rows = [["Requirement", "Test cases", "Status", "Notes"]]
        for req, tcs, note, *forced in REQ_MATRIX:
            st = [statuses[t] for t in tcs]
            status = ("Pass" if all(x == "Pass" for x in st) else "Not Implemented" if all(x == "Not Implemented"
                      for x in st) else "Not Executed" if all(x == "Not Executed" for x in st) else
                      "Fail" if any(x == "Fail" for x in st) else "Partial") if st else "Not Executed"
            status = forced[0] if forced else status
            req_rows.append([req, ", ".join(tcs) or "-", status, note])
        s.append(table(req_rows, [w * .16, w * .2, w * .14, w * .5], status_col=2))
        s += [P("5. Defects", "h1")]
        s.append(table([["ID", "Severity", "Description", "Status"]] + [list(d) for d in DEFECTS],
                       [w * .08, w * .1, w * .64, w * .18], status_col=3))
        s += [P("6. Deviations from SRS / SAD (for the demo)", "h1")]
        s.append(table([["Area", "Original", "As built"]] + [list(d) for d in DEVIATIONS],
                       [w * .16, w * .38, w * .46]))
        s += [P("7. Conclusion", "h1"),
              P("All implemented core use cases (submit, categorise, route, track, resolve, escalate, notify, "
                "monitor SLA, dashboard, RBAC) pass end-to-end. The system is not yet release-ready for "
                "multi-user load: DEF-01 must be merged before NFR-001 is load-tested. FR-008 (ratings, auto-close) "
                "and the FR-012 immutable audit log are not implemented and are carried into Sprint 3 together "
                "with the 70% NLP threshold and per-category SLA rules.")]
        return s
    meta_commit = dict(meta).get("Commit tested", "")
    build(DOCS / "System_Validation_Report.pdf", "System Validation Report", "Software Engineering Mini-Project - Part 3",
          meta, story)
    return statuses


REQ_MATRIX = [
    ("FR-001 Submission", ["TC01", "TC02", "TC03", "TC04"], "Limits, image checks and GPS validated."),
    ("FR-002 NLP categories", ["TC05", "TC06", "TC28"], "Top-3 + override pass; 70% threshold not implemented."),
    ("FR-003 Ticket ID", ["TC07"], "Sequential uniqueness passes; concurrent uniqueness fails on main (DEF-01).", "Partial"),
    ("FR-004 Routing", ["TC08", "TC09", "TC28"], "Department, zone, workload and supervisor fallback."),
    ("FR-005 Lifecycle", ["TC10", "TC23"], "All transitions logged with time and actor."),
    ("FR-006 SLA", ["TC11", "TC12", "TC27"], "Severity-based rules; per-category rules pending."),
    ("FR-007 Notifications", ["TC13", "TC25"], "In-app, email, opt-in SMS."),
    ("FR-008 Rating / auto-close", ["TC14", "TC15"], "Not built; Sprint 3 Task 2."),
    ("FR-009 Escalation", ["TC16"], "Priority queue and SLA reset."),
    ("FR-010 RBAC", ["TC17", "TC26"], "45 role/endpoint checks; user update/deactivate pending."),
    ("FR-011 Dashboard", ["TC18", "TC24"], "KPIs, filters, CSV, 60 s refresh; CSAT N/A."),
    ("FR-012 Audit log", ["TC19"], "Actor + time recorded, not tamper-proof; Sprint 3 Task 3."),
    ("FR-013 Resolution", ["TC22"], "Resolution notes required; citizen notified."),
    ("FR-014 Notes / evidence", ["TC21", "TC22"], "10 MB limit, content-type check, staff-only notes."),
    ("NFR-001 Performance", ["TC20"], "Load test not executed; single-client smoke only."),
    ("NFR-002 Security", ["TC26"], "App-level controls pass (bcrypt, JWT, RBAC, file signatures). TLS 1.3 and "
     "AES-256 at rest are deployment concerns and were not tested.", "Partial"),
    ("NFR-003 Availability", [], "Not tested: needs a deployed environment. Data-loss risk under concurrency (DEF-01)."),
]
DEFECTS = [
    ("DEF-01", "High", "Concurrent submissions on main (commit 66d1420): 20 simultaneous requests gave 5-9 successful "
     "responses, duplicate ticket IDs, and in one run left complaints_store.json unreadable (JSONDecodeError). "
     "Cause: read-modify-write of the JSON file without locking or atomic replace. Fix exists on branch "
     "feature/concurrency-safe-storage (Sprint 3 Task 1): re-running the same 20-request check there gave 20/20 "
     "unique IDs, all stored.", "Fixed on branch"),
    ("DEF-02", "Medium", "FR-008 rating, feedback and 7-day auto-close not implemented; dashboard CSAT always N/A.", "Open"),
    ("DEF-03", "Medium", "FR-012: no immutable audit log; history is stored inside the editable complaint record.", "Open"),
    ("DEF-04", "Low", "FR-002: no 70% confidence threshold or low-confidence prompt.", "Open"),
    ("DEF-05", "Low", "FR-006: SLA hours depend on severity only, not category and severity.", "Open"),
]
DEVIATIONS = [
    ("Architecture", "Lab 3 justification: microservices (6 services behind an API gateway, each with its own "
     "data store).",
     "Single Flask application with blueprints per service and JSON file storage. Module boundaries match the "
     "SAD components, so services can be split out later."),
    ("Category field", "Mandatory on submission.", "Optional; the top NLP suggestion is used when left empty."),
    ("Lifecycle", "Linear New -> ... -> Closed.", "Citizen can reopen a Resolved complaint (back to In Progress)."),
    ("Confirmation", "Shows a timeline link.", "Shows ticket ID and category; timeline is on the Track page."),
    ("Notifications", "Sent through an asynchronous queue so a slow provider never blocks a request.",
     "Sent inside the request; a provider failure is caught and logged so the request still succeeds, but a slow "
     "provider adds latency (up to the 10 s timeout)."),
    ("Evidence", "Agents attach files (FR-014).", "Supervisors and admins may also attach evidence."),
]


def test_case_doc(junit, meta, statuses):
    def story(w):
        s = [P("1. What changed", "h1"),
             P("This updates the Test Plan test cases (v1.0, TC01-TC20) to match what was built in Sprints 1 and 2. "
               "Expected results were revised where the design changed, TC21-TC28 were added for new behaviour, "
               "and every case now records its actual result, status and the automated tests that execute it. "
               "Status is computed from the latest automated run: a case passes only if all of its tests pass. "
               "Concurrency cases UT-04 to UT-09 / IT-04 for Sprint 3 Task 1 are kept in "
               "Documents/Sprint_3_Test_Cases.md on branch feature/concurrency-safe-storage."),
             ]
        counts = OrderedDict((k, 0) for k in ("Pass", "Fail", "Partial", "Not Implemented", "Not Executed"))
        for v in statuses.values():
            counts[v] += 1
        s.append(P("Summary: " + ", ".join(f"<b>{v}</b> {k}" for k, v in counts.items()) + f" (of {len(CASES)})."))
        s.append(P("2. Test cases", "h1"))
        rows = [["ID", "Req", "Scenario", "Preconditions", "Test steps", "Test data", "Expected result",
                 "Actual result", "Pri.", "Status"]]
        for c in CASES:
            rows.append([c["id"], c["req"], c["scenario"], c["pre"], c["steps"], c["data"], c["expected"],
                         c["actual"], c["priority"], statuses[c["id"]]])
        s.append(table(rows, [w * x for x in (.045, .06, .1, .1, .17, .11, .14, .14, .045, .09)], status_col=9))
        s += [PageBreak(), P("3. Changes since Test Plan v1.0 and automation mapping", "h1")]
        rows = [["ID", "Change", "Automated tests (tests/...)", "Status"]]
        for c in CASES:
            rows.append([c["id"], c["change"], "\n".join(short(t) for t in c["tests"]) or "Manual / not automated",
                         statuses[c["id"]]])
        s.append(table(rows, [w * .06, w * .42, w * .42, w * .1], status_col=3))
        s += [P("4. Traceability (requirement -> test cases)", "h1")]
        rows = [["Requirement", "Test cases"]] + [[r, ", ".join(t) or "-"] for r, t, *_ in REQ_MATRIX]
        s.append(table(rows, [w * .3, w * .7]))
        return s
    build(DOCS / "Test_Cases_Updated.pdf", "Test Case Document (Updated)", "Version 2.0 - after Sprint 2", meta,
          story, landscape_mode=True)


def main():
    if "--no-run" in sys.argv:   # rebuild the PDFs from the last run's raw results
        code = 0
        m = re.search(r"SV-10 latency over (\d+) requests: median ([\d.]+) ms, p99 ([\d.]+) ms",
                      (RAW / "pytest-output.txt").read_text())
        latency = m.groups() if m else None
    else:
        code, latency = run_suite()
    junit = load_junit()
    cov = json.loads((RAW / "coverage.json").read_text())
    passed = sum(t["outcome"] == "Pass" for t in junit.values())
    meta = [("Version", "1.0"), ("Date of execution", datetime.now().strftime("%d %b %Y, %H:%M")),
            ("Commit tested", git("rev-parse", "--short", "HEAD") or "n/a"),
            ("Branch", git("rev-parse", "--abbrev-ref", "HEAD") or "n/a"),
            ("Test framework", "pytest, pytest-cov (coverage.py), pytest-html"),
            ("Overall result", f"{passed} of {len(junit)} automated tests passed")]
    unit_report(junit, meta)
    statuses = system_report(junit, meta, latency)
    coverage_reports(cov, meta)
    test_case_doc(junit, meta, statuses)
    print(f"pytest exit code {code}; {passed}/{len(junit)} passed; reports written to {DOCS}")
    return code


if __name__ == "__main__":
    sys.exit(main())
