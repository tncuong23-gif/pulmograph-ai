"""Optional spelling suggestions; never silently rewrite recognized clinical facts."""
import re
import unicodedata


def dialect_suggestion(text: str) -> str | None:
    text = unicodedata.normalize('NFC', text)
    replacements = {'tui': 'tôi', 'hổng': 'không', 'bịnh': 'bệnh'}
    def replace(match):
        source = match.group(0)
        value = replacements[source.casefold()]
        return value.capitalize() if source[0].isupper() else value
    suggestion = re.sub(r'\b(?:tui|hổng|bịnh)\b', replace, text, flags=re.IGNORECASE)
    # In particular, "hông" can refer to a body part. Do not replace it blindly.
    return suggestion if suggestion != text else None
