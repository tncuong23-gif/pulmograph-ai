from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


SECTION_NAMES = (
    "hoibenh_quatrinhbenhly",
    "khambenh_toanthan",
    "caccoquan_hohap",
    "caccoquan_tuanhoan",
    "tiensubenh_banthan",
    "tongketba_tomtat_kqxn_cls_cogiatrichandoan",
    "tongketba_quatrinhbenhly_dienbienlamsang",
)

SECTION_PATTERN = re.compile(
    r"^\s*(?P<name>" + "|".join(map(re.escape, SECTION_NAMES)) + r")\s*:\s*(?P<value>.*)$",
    re.IGNORECASE,
)

EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){8,10}(?!\d)")
PATIENT_ID_PATTERN = re.compile(
    r"(?i)\b(?:cccd|cmnd|mã\s*(?:số\s*)?(?:bn|bệnh\s*nhân)|msbn)"
    r"\s*[:#\-]?\s*[A-Z0-9][A-Z0-9.\-]{3,}"
)

BOUNDARY_PATTERN = re.compile(r"\n+|;\s*|[!?]\s+|\.(?=\s+[A-ZÀ-Ỹ+*\-])\s*")


@dataclass(frozen=True)
class ParsedDocument:
    doc_id: str
    disease: str
    relative_path: str
    content_hash: str
    text: str
    sections: list[dict]
    pii_counts: dict[str, int]


def stable_id(value: str, prefix: str = "DOC") -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t\f\v]+", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def anonymize_text(text: str) -> tuple[str, dict[str, int]]:
    counts: Counter[str] = Counter()

    def replace(pattern: re.Pattern[str], replacement: str, key: str, value: str) -> str:
        def _sub(_: re.Match[str]) -> str:
            counts[key] += 1
            return replacement

        return pattern.sub(_sub, value)

    text = replace(EMAIL_PATTERN, "[EMAIL]", "email", text)
    text = replace(PATIENT_ID_PATTERN, "[PATIENT_ID]", "patient_id", text)
    text = replace(PHONE_PATTERN, "[PHONE]", "phone", text)
    return text, dict(counts)


def parse_sections(text: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current_name = "unstructured"
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        value = normalize_text("\n".join(current_lines))
        if value:
            sections.append({"name": current_name, "text": value})
        current_lines = []

    for line in text.splitlines():
        match = SECTION_PATTERN.match(line)
        if match:
            flush()
            current_name = match.group("name").lower()
            current_lines = [match.group("value")]
        else:
            current_lines.append(line)
    flush()

    if not sections and text.strip():
        sections.append({"name": "unstructured", "text": normalize_text(text)})
    return sections


def canonical_content(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def parse_document(path: Path, input_root: Path) -> ParsedDocument:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    normalized = normalize_text(raw)
    anonymized, pii_counts = anonymize_text(normalized)
    sections = parse_sections(anonymized)

    cursor = 0
    document_parts: list[str] = []
    enriched_sections: list[dict] = []
    for section in sections:
        if document_parts:
            document_parts.append("\n")
            cursor += 1
        start = cursor
        document_parts.append(section["text"])
        cursor += len(section["text"])
        enriched_sections.append(
            {
                "name": section["name"],
                "text": section["text"],
                "doc_start": start,
                "doc_end": cursor,
            }
        )

    text = "".join(document_parts)
    relative_path = path.relative_to(input_root).as_posix()
    disease = path.parent.name
    doc_id = stable_id(relative_path)
    content_hash = hashlib.sha256(canonical_content(text).encode("utf-8")).hexdigest()
    return ParsedDocument(
        doc_id=doc_id,
        disease=disease,
        relative_path=relative_path,
        content_hash=content_hash,
        text=text,
        sections=enriched_sections,
        pii_counts=pii_counts,
    )


def _trimmed_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def sentence_unit_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in BOUNDARY_PATTERN.finditer(text):
        span = _trimmed_span(text, cursor, match.start())
        if span:
            spans.append(span)
        cursor = match.end()
    final = _trimmed_span(text, cursor, len(text))
    if final:
        spans.append(final)
    return spans


def _hard_split(text: str, start: int, end: int, max_chars: int) -> Iterator[tuple[int, int]]:
    cursor = start
    while end - cursor > max_chars:
        proposed = cursor + max_chars
        boundary = text.rfind(" ", cursor + max_chars // 2, proposed)
        if boundary <= cursor:
            boundary = proposed
        span = _trimmed_span(text, cursor, boundary)
        if span:
            yield span
        cursor = boundary
    span = _trimmed_span(text, cursor, end)
    if span:
        yield span


def segment_section(
    text: str,
    *,
    min_chars: int = 60,
    max_chars: int = 800,
    max_units: int = 3,
) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    for start, end in sentence_unit_spans(text):
        if end - start > max_chars:
            units.extend(_hard_split(text, start, end, max_chars))
        else:
            units.append((start, end))

    chunks: list[tuple[int, int]] = []
    index = 0
    while index < len(units):
        start, end = units[index]
        used = 1
        while index + used < len(units) and used < max_units:
            next_end = units[index + used][1]
            if next_end - start > max_chars:
                break
            if end - start >= min_chars:
                break
            end = next_end
            used += 1
        chunks.append((start, end))
        index += used
    return chunks


def iter_segments(document: dict) -> Iterator[dict]:
    for section_index, section in enumerate(document["sections"]):
        for start, end in segment_section(section["text"]):
            text = section["text"][start:end]
            if not text.strip():
                continue
            segment_key = f"{document['doc_id']}:{section_index}:{start}:{end}"
            yield {
                "segment_id": stable_id(segment_key, prefix="SEG"),
                "doc_id": document["doc_id"],
                "disease_labels": document["disease_labels"],
                "section": section["name"],
                "text": text,
                "section_start": start,
                "section_end": end,
                "doc_start": section["doc_start"] + start,
                "doc_end": section["doc_start"] + end,
            }


def collect_section_counts(documents: Iterable[dict]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for document in documents:
        counts.update(section["name"] for section in document["sections"])
    return counts


def group_by_content(documents: Iterable[ParsedDocument]) -> tuple[list[dict], list[dict]]:
    grouped: dict[str, list[ParsedDocument]] = defaultdict(list)
    for document in documents:
        grouped[document.content_hash].append(document)

    unique_documents: list[dict] = []
    duplicate_groups: list[dict] = []
    for content_hash in sorted(grouped):
        members = sorted(grouped[content_hash], key=lambda item: item.relative_path)
        representative = members[0]
        disease_labels = sorted({member.disease for member in members})
        unique_documents.append(
            {
                "doc_id": representative.doc_id,
                "content_hash": content_hash,
                "disease_labels": disease_labels,
                "text": representative.text,
                "sections": representative.sections,
                "pii_counts": dict(
                    sum((Counter(member.pii_counts) for member in members), Counter())
                ),
                "duplicate_count": len(members),
                "label_conflict": len(disease_labels) > 1,
            }
        )
        if len(members) > 1:
            duplicate_groups.append(
                {
                    "group_id": stable_id(content_hash, prefix="DUP"),
                    "content_hash": content_hash,
                    "member_count": len(members),
                    "disease_labels": disease_labels,
                    "doc_ids": [member.doc_id for member in members],
                    "label_conflict": len(disease_labels) > 1,
                }
            )
    return unique_documents, duplicate_groups

