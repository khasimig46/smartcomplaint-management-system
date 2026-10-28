"""Tasks 3 & 4: Generate category predictions with confidence scores."""
import joblib

from nlp.preprocess import clean_text
from nlp.train_model import MODEL_PATH, train

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = joblib.load(MODEL_PATH) if MODEL_PATH.exists() else train()
    return _model


def get_categories():
    return sorted(_get_model().classes_.tolist())


def suggest_categories(text: str, top_n: int = 3):
    """Return the top N categories with confidence (percent)."""
    model = _get_model()
    probs = model.predict_proba([clean_text(text)])[0]
    ranked = sorted(zip(model.classes_, probs), key=lambda x: -x[1])[:top_n]
    return [{"category": c, "confidence": round(float(p) * 100, 1)} for c, p in ranked]
