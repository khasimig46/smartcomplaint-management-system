import pytest

from nlp.categorizer import suggest_categories


@pytest.fixture
def client(app):
    return app.test_client()


def test_top_3_categories_suggested():
    result = suggest_categories("Water is not coming from the tap")
    assert len(result) == 3


def test_confidence_score_present():
    result = suggest_categories("Big pothole on the road")
    assert all(0 <= r["confidence"] <= 100 for r in result)


def test_correct_category_ranked_first():
    assert suggest_categories("Street light not working, power cut")[0]["category"] == "Electricity"


def test_user_can_override_suggestion(client):
    c = client.post("/submit-complaint", json={"text": "Garbage not collected"}).get_json()
    r = client.post("/override-category", json={"complaint_id": c["id"], "category": "Roads"})
    assert r.get_json()["category"] == "Roads"
    assert r.get_json()["overridden"] is True


def test_empty_text_rejected(client):
    assert client.post("/suggest-category", json={"text": ""}).status_code == 400
