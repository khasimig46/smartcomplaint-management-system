"""Task 2: Process complaint text."""
import re

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "of", "to",
    "for", "and", "or", "my", "our", "it", "this", "that", "with", "has", "have",
    "been", "be", "i", "we", "there", "from", "by", "as", "very", "too",
}


def clean_text(text: str) -> str:
    """Lowercase, strip punctuation/digits and remove stopwords."""
    text = (text or "").lower()
    text = re.sub(r"[^a-z\s]", " ", text)
    tokens = [t for t in text.split() if t not in STOPWORDS]
    return " ".join(tokens)
