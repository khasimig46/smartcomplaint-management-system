"""Tasks 3 & 4: Generate category predictions with confidence scores."""
import joblib
import sklearn

from nlp.preprocess import clean_text
from nlp.train_model import MODEL_PATH, train

_model = None
CONFIDENCE_THRESHOLD = 70


def _get_model():
    global _model
    if _model is not None:
        return _model
    if MODEL_PATH.exists():
        try:
            saved = joblib.load(MODEL_PATH)
            if not isinstance(saved, dict) or saved.get("sklearn_version") != sklearn.__version__ or "model" not in saved:
                raise ValueError("Saved model metadata/version is incompatible")
            _model = saved["model"]
        except Exception:
            _model = train()
    else:
        _model = train()
    return _model


def get_categories():
    return sorted(_get_model().classes_.tolist())


def suggest_categories(text: str, top_n: int = 3):
    """Return the top N categories with confidence and a 70% confidence flag."""
    model = _get_model()
    probs = model.predict_proba([clean_text(text)])[0]
    ranked = sorted(zip(model.classes_, probs), key=lambda x: -x[1])[:top_n]
    return [
        {"category": category, "confidence": round(float(probability) * 100, 1),
         "confident": round(float(probability) * 100, 1) >= CONFIDENCE_THRESHOLD}
        for category, probability in ranked
    ]
