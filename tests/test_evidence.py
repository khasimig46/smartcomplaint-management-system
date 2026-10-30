import io

import pytest

from conftest import complaint_body
from services import evidence

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100
PDF = b"%PDF-1.7\n" + b"0" * 100


@pytest.fixture
def setup(app, make_user, login, citizen):
    make_user("agent", email="ag@test.com", name="Ravi", department="Water Department")
    make_user("supervisor", email="sup@test.com")
    c = app.test_client()
    comp = c.post("/submit-complaint", json=complaint_body(category="Water Supply"), headers=citizen).get_json()
    return c, comp, {"citizen": citizen, "agent": login("ag@test.com"), "sup": login("sup@test.com")}


def upload(c, cid, headers, *files):
    data = {"files": [(io.BytesIO(body), name) for name, body in files]}
    return c.post(f"/complaints/{cid}/evidence", data=data, headers=headers, content_type="multipart/form-data")


def test_images_and_pdfs_upload_successfully(setup, tmp_path):
    c, comp, hdr = setup
    r = upload(c, comp["id"], hdr["agent"], ("pipe.jpg", JPEG), ("site.png", PNG), ("report.pdf", PDF))
    assert r.status_code == 201
    added = r.get_json()
    assert [e["content_type"] for e in added] == ["image/jpeg", "image/png", "application/pdf"]
    assert [e["filename"] for e in added] == ["pipe.jpg", "site.png", "report.pdf"]
    assert all(e["uploaded_by_name"] == "Ravi" and e["uploaded_at"] for e in added)
    assert (tmp_path / added[2]["path"]).read_bytes() == PDF


def test_files_linked_to_complaint(setup):
    c, comp, hdr = setup
    upload(c, comp["id"], hdr["agent"], ("a.jpg", JPEG))
    upload(c, comp["id"], hdr["sup"], ("b.pdf", PDF))
    stored = c.get(f"/complaints/{comp['id']}", headers=hdr["citizen"]).get_json()["evidence"]
    assert [e["id"] for e in stored] == ["E1", "E2"]
    assert [e["filename"] for e in c.get(f"/complaints/{comp['id']}/evidence", headers=hdr["sup"]).get_json()] == ["a.jpg", "b.pdf"]


def test_invalid_files_rejected(setup):
    c, comp, hdr = setup
    r = upload(c, comp["id"], hdr["agent"], ("virus.exe", b"MZ\x90\x00" + b"0" * 100))
    assert r.status_code == 400 and "not a PDF, JPEG or PNG" in r.get_json()["error"]
    assert upload(c, comp["id"], hdr["agent"], ("fake.pdf", b"just text")).status_code == 400
    assert upload(c, comp["id"], hdr["agent"]).status_code == 400
    too_many = [(f"{i}.jpg", JPEG) for i in range(evidence.MAX_FILES + 1)]
    assert upload(c, comp["id"], hdr["agent"], *too_many).status_code == 400
    assert "evidence" not in c.get(f"/complaints/{comp['id']}", headers=hdr["sup"]).get_json()


def test_file_size_validated(setup):
    c, comp, hdr = setup
    r = upload(c, comp["id"], hdr["agent"], ("big.pdf", PDF + b"0" * evidence.MAX_FILE_BYTES))
    assert r.status_code == 400 and "10 MB" in r.get_json()["error"]
    assert upload(c, comp["id"], hdr["agent"], ("6mb.jpg", JPEG + b"0" * (6 * 1024 * 1024))).status_code == 201


def test_only_assigned_agent_or_supervisor_can_upload(setup, make_user, login):
    c, comp, hdr = setup
    make_user("agent", email="other@test.com", department="Water Department")
    assert upload(c, comp["id"], login("other@test.com"), ("a.jpg", JPEG)).status_code == 403
    assert upload(c, comp["id"], hdr["citizen"], ("a.jpg", JPEG)).status_code == 403
    assert upload(c, "SCMS-20260101-99999", hdr["sup"], ("a.jpg", JPEG)).status_code == 404
    assert upload(c, comp["id"], hdr["sup"], ("a.jpg", JPEG)).status_code == 201


def test_download_evidence(setup, make_user, login):
    c, comp, hdr = setup
    upload(c, comp["id"], hdr["agent"], ("report.pdf", PDF))
    r = c.get(f"/complaints/{comp['id']}/evidence/E1", headers=hdr["citizen"])
    assert r.status_code == 200 and r.data == PDF and r.mimetype == "application/pdf"
    assert "report.pdf" in r.headers["Content-Disposition"]
    assert c.get(f"/complaints/{comp['id']}/evidence/E9", headers=hdr["agent"]).status_code == 404
    make_user(email="stranger@test.com")
    assert c.get(f"/complaints/{comp['id']}/evidence/E1", headers=login("stranger@test.com")).status_code == 403


def test_closed_complaint_rejects_evidence(setup):
    c, comp, hdr = setup
    for s in ("In Progress", "Resolved"):
        c.patch(f"/complaints/{comp['id']}/status", json={"status": s}, headers=hdr["agent"])
    c.patch(f"/complaints/{comp['id']}/status", json={"status": "Closed"}, headers=hdr["citizen"])
    r = upload(c, comp["id"], hdr["agent"], ("late.jpg", JPEG))
    assert r.status_code == 400 and "closed" in r.get_json()["error"]


def test_file_type_detected_by_signature():
    assert evidence.file_type(PDF[:8]) == (".pdf", "application/pdf")
    assert evidence.file_type(PNG[:8]) == (".png", "image/png")
    assert evidence.file_type(b"GIF89a") is None
