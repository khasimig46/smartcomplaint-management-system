import io

from conftest import complaint_body

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def form(**overrides):
    return complaint_body(**overrides)


def test_complaint_submitted_successfully(app, citizen):
    r = app.test_client().post("/submit-complaint", json=form(), headers=citizen)
    assert r.status_code == 201
    c = r.get_json()
    assert c["title"] == "Water leakage" and c["severity"] == "High"
    assert c["id"].startswith("SCMS-")


def test_images_uploaded_correctly(app, citizen, tmp_path):
    data = form()
    data["images"] = [(io.BytesIO(JPEG), "a.jpg"), (io.BytesIO(PNG), "b.png")]
    r = app.test_client().post("/submit-complaint", data=data, headers=citizen, content_type="multipart/form-data")
    assert r.status_code == 201
    imgs = r.get_json()["images"]
    assert len(imgs) == 2
    assert (tmp_path / imgs[0]).read_bytes() == JPEG


def test_gps_coordinates_stored(app, citizen):
    r = app.test_client().post("/submit-complaint", json=form(latitude="12.9716", longitude="77.5946"), headers=citizen)
    assert r.get_json()["location"] == {"latitude": 12.9716, "longitude": 77.5946}


def test_validation_errors_shown(app, citizen):
    c = app.test_client()
    r = c.post("/submit-complaint", json=form(title="", severity="Urgent"), headers=citizen)
    assert r.status_code == 400
    assert set(r.get_json()["fields"]) == {"title", "severity"}
    assert "title" in c.post("/submit-complaint", json=form(title="x" * 121), headers=citizen).get_json()["fields"]
    assert "location" in c.post("/submit-complaint", json=form(latitude="200", longitude="0"), headers=citizen).get_json()["fields"]


def test_oversized_image_rejected(app, citizen):
    data = form()
    data["images"] = [(io.BytesIO(JPEG + b"0" * (5 * 1024 * 1024)), "big.jpg")]
    r = app.test_client().post("/submit-complaint", data=data, headers=citizen, content_type="multipart/form-data")
    assert r.status_code == 400 and "5 MB" in r.get_json()["fields"]["images"]


def test_non_image_and_too_many_images_rejected(app, citizen):
    c = app.test_client()
    data = form(); data["images"] = [(io.BytesIO(b"not an image"), "x.txt")]
    assert "images" in c.post("/submit-complaint", data=data, headers=citizen, content_type="multipart/form-data").get_json()["fields"]
    data = form(); data["images"] = [(io.BytesIO(JPEG), f"{i}.jpg") for i in range(6)]
    assert "images" in c.post("/submit-complaint", data=data, headers=citizen, content_type="multipart/form-data").get_json()["fields"]


def test_login_required_and_only_citizens_submit(app, make_user, login):
    c = app.test_client()
    assert c.post("/submit-complaint", json=form()).status_code == 401
    make_user("agent", email="ag@test.com", department="Water Department")
    assert c.post("/submit-complaint", json=form(), headers=login("ag@test.com")).status_code == 403


def test_citizen_sees_only_own_complaints(app, make_user, login, citizen):
    c = app.test_client()
    c.post("/submit-complaint", json=form(), headers=citizen)
    make_user(email="other@test.com")
    other = login("other@test.com")
    assert len(c.get("/complaints/mine", headers=citizen).get_json()) == 1
    assert c.get("/complaints/mine", headers=other).get_json() == []
