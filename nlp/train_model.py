"""Task 1: Integrate NLP model (TF-IDF + Logistic Regression)."""
from pathlib import Path

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
        TfidfVectorizer(ngram_range=(1, 2)),
        LogisticRegression(max_iter=1000),
    )
    model.fit(X, df["category"])
    MODEL_PATH.parent.mkdir(exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    return model


if __name__ == "__main__":
    train()
    print(f"Model trained and saved to {MODEL_PATH}")
