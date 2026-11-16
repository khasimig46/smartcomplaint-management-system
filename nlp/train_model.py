"""Task 1: Integrate NLP model (TF-IDF + Logistic Regression)."""
from pathlib import Path
import sklearn
from sklearn.model_selection import StratifiedKFold, cross_val_score

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from nlp.preprocess import clean_text

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "complaints.csv"
MODEL_PATH = BASE_DIR / "models" / "category_model.pkl"


def train():
    df = pd.read_csv(DATA_PATH)
    X = df["text"].apply(clean_text)
    model = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), analyzer="char_wb", sublinear_tf=True),
        LogisticRegression(C=4.0, max_iter=2000),
    )
    model.fit(X, df["category"])
    MODEL_PATH.parent.mkdir(exist_ok=True)
    joblib.dump({"model": model, "sklearn_version": sklearn.__version__}, MODEL_PATH)
    return model


def cross_validated_accuracy():
    df = pd.read_csv(DATA_PATH)
    X = df["text"].apply(clean_text)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    model = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), analyzer="char_wb", sublinear_tf=True),
                          LogisticRegression(C=4.0, max_iter=2000))
    scores = cross_val_score(model, X, df["category"], cv=cv, scoring="accuracy")
    return {"fold_accuracy": [round(float(x), 4) for x in scores],
            "mean_accuracy": round(float(scores.mean()), 4)}


if __name__ == "__main__":
    train()
    print(f"Model trained and saved to {MODEL_PATH}")
    print(f"Cross-validation: {cross_validated_accuracy()}")
