import re
import unicodedata


def normalize_whitespace(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalized_key(text: str) -> str:
    text = normalize_whitespace(text).casefold()
    text = re.sub(r"[^\w\s-]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def token_set(text: str) -> set[str]:
    return {token for token in normalized_key(text).split() if len(token) > 1}
