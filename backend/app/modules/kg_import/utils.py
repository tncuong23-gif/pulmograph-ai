from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_import_id() -> str:
    return "IMP_" + uuid.uuid4().hex[:12].upper()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_of(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


_WS = re.compile(r"\s+")


def clean_text(value: str) -> str:
    """Explicit normalization rule: NFC + trim + collapse internal whitespace."""
    return _WS.sub(" ", unicodedata.normalize("NFC", value)).strip()


def fold(value: str) -> str:
    """normalized_name rule: cleaned text, case-folded (no accent stripping: it changes medical meaning)."""
    return clean_text(value).casefold()


def chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
