"""TC06 / FR-002 / UC-07 3a: 70% NLP confidence threshold (Sprint 3 Task 5)."""
import pytest

from nlp.categorizer import CONFIDENCE_THRESHOLD, suggest_categories
from tests.conftest import complaint_body

SRS_EXAMPLE = "water leakage from main pipe on 5th cross"
VAGUE = "something is wrong here please look into it"


@pytest.fixture
def client(app):
    return app.test_client()


def test_threshold_is_70_percent():
    assert CONFIDENCE_THRESHOLD == 70


def test_confident_flag_follows_the_threshold():
    for text in (SRS_EXAMPLE, VAGUE, "pothole on the main road near the school"):
        for s in suggest_categories(text):
            assert s["confident"] == (s["confidence"] >= CONFIDENCE_THRESHOLD)


def test_srs_example_is_confident_water_supply():
    top = suggest_categories(SRS_EXAMPLE)[0]
    assert top["category"] == "Water Supply"
    assert top["confident"] and top["confidence"] >= 70


def test_vague_text_is_flagged_low_confidence():
    assert not any(s["confident"] for s in suggest_categories(VAGUE))


def test_suggest_endpoint_returns_confident_flag(client):
    data = client.post("/suggest-category", json={"text": VAGUE}).get_json()
    assert len(data) == 3 and all(s["confident"] is False for s in data)


def test_low_confidence_submission_without_category_asks_citizen_to_choose(app, citizen):
    c = app.test_client()
    r = c.post("/submit-complaint", headers=citizen, json=complaint_body(title="Problem", description=VAGUE))
    assert r.status_code == 400
    body = r.get_json()
    assert "category" in body["fields"] and "70%" in body["error"]
    assert len(body["suggestions"]) == 3
    assert c.get("/complaints/mine", headers=citizen).get_json() == []      # nothing saved


def test_low_confidence_submission_continues_once_category_chosen(app, citizen):
    r = app.test_client().post("/submit-complaint", headers=citizen,
                               json=complaint_body(title="Problem", description=VAGUE, category="Sanitation"))
    assert r.status_code == 201
    assert r.get_json()["category"] == "Sanitation"


def test_confident_submission_without_category_uses_top_suggestion(app, citizen):
    r = app.test_client().post("/submit-complaint", headers=citizen,
                               json=complaint_body(title="Water leakage", description=SRS_EXAMPLE))
    assert r.status_code == 201
    assert r.get_json()["category"] == "Water Supply" and r.get_json()["overridden"] is False
