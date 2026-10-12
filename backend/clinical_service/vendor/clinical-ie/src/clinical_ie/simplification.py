from __future__ import annotations

import hashlib
import re
from collections import Counter
from copy import deepcopy
from typing import Iterable

from .training import LEARNED_RELATIONS


SENTENCE_OPEN = "<extra_id_0>"
SENTENCE_CLOSE = "<extra_id_1>"
LEGACY_SENTENCE_OPEN = "<SENT>"
LEGACY_SENTENCE_CLOSE = "</SENT>"
ANNOTATION_METHOD = "lossless_relation_safe_clause_decomposition_v3"
GENERATED_SENTENCE_PATTERN = re.compile(
    r"<extra_id_0>\s*(.*?)\s*<extra_id_1>",
    re.IGNORECASE | re.DOTALL,
)
LEGACY_GENERATED_SENTENCE_PATTERN = re.compile(
    r"<SENT>\s*(.*?)\s*</SENT>",
    re.IGNORECASE | re.DOTALL,
)

# These separators are common in the de-identified records. Decimal punctuation
# and punctuation that belongs to an annotated entity are rejected later by the
# protected-span check.
SEPARATOR_PATTERN = re.compile(
    r"\r?\n+|"
    r"\s*(?:=>|->|→)\s*|"
    r"\s+\+\s+|"
    r"\s+-\s+|"
    r"[;|]+\s*|"
    r"(?<!\d),+\s*|,+(?!\s*\d)\s*|"
    r"(?<!\d)[.!?]+(?!\d)\s*|"
    r"/(?=\s+[A-ZÀ-Ỹ])",
    re.IGNORECASE,
)

CONNECTOR_PATTERN = re.compile(
    r"\s+(?:và|nhưng|sau\s+đó|kèm\s+theo|kèm|đồng\s+thời)\s+",
    re.IGNORECASE,
)

# ``+``, ``++`` and ``+++`` are clinical qualitative results, so they must never
# be stripped from the edge of a generated sentence. A standalone list `` + ``
# is already consumed by ``SEPARATOR_PATTERN``.
EDGE_TRIM_CHARS = " \t\r\n,;|"


def parse_generated_simple_sentences(text: str) -> list[str]:
    """Parse v1.2 T5 sentinels and legacy v1.1 tags.

    The sentinel tokens already exist in the ViT5 vocabulary, so v1.2 does not
    resize the embedding table.  Legacy support keeps downloaded v1.1 models
    usable by the same local inference pipeline.
    """
    for pattern in (GENERATED_SENTENCE_PATTERN, LEGACY_GENERATED_SENTENCE_PATTERN):
        sentences = [match.strip() for match in pattern.findall(text) if match.strip()]
        if sentences:
            return sentences
    untagged = re.sub(
        r"(?:<extra_id_[01]>|</?SENT>)",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return [part.strip() for part in re.split(r"\r?\n+", untagged) if part.strip()]


def _stable_hash(*values: object) -> str:
    payload = "\x1f".join(str(value) for value in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _learned_relations(record: dict) -> list[dict]:
    return [
        relation
        for relation in record.get("relations", [])
        if str(relation.get("predicate", "")).casefold() in LEARNED_RELATIONS
    ]


def _protected_intervals(record: dict) -> list[tuple[int, int]]:
    entities = {
        entity["id"]: entity
        for entity in record.get("entities", [])
    }
    intervals = [
        (int(entity["start"]), int(entity["end"]))
        for entity in entities.values()
    ]
    for relation in _learned_relations(record):
        head = entities.get(relation.get("subject"))
        tail = entities.get(relation.get("object"))
        if not head or not tail:
            continue
        intervals.append((
            min(int(head["start"]), int(tail["start"])),
            max(int(head["end"]), int(tail["end"])),
        ))
    # Punctuation inside parentheses often belongs to a dosage, lab note, or
    # clinical aside. Keeping the entire balanced group together prevents targets
    # such as "(Hct 39,7%." and "TC 107).".
    stack: list[tuple[str, int]] = []
    closing = {")": "(", "]": "[", "}": "{"}
    for index, char in enumerate(record.get("text", "")):
        if char in "([{":
            stack.append((char, index))
        elif char in closing:
            for position in range(len(stack) - 1, -1, -1):
                opener, start = stack[position]
                if opener == closing[char]:
                    del stack[position:]
                    intervals.append((start, index + 1))
                    break
    return intervals


def _cut_is_protected(start: int, end: int, intervals: list[tuple[int, int]]) -> bool:
    # A separator is unsafe when it overlaps an entity or lies between the two
    # endpoints of a learned relation.
    return any(start < protected_end and end > protected_start for protected_start, protected_end in intervals) or any(
        protected_start < start < protected_end
        or protected_start < end < protected_end
        for protected_start, protected_end in intervals
    )


def _has_entity_on_each_side(
    record: dict,
    start: int,
    end: int,
    left_boundary: int,
    right_boundary: int,
) -> bool:
    left = any(
        left_boundary <= int(entity["start"])
        and int(entity["end"]) <= start
        for entity in record.get("entities", [])
    )
    right = any(
        end <= int(entity["start"])
        and int(entity["end"]) <= right_boundary
        for entity in record.get("entities", [])
    )
    return left and right


def _trim_range(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start] in EDGE_TRIM_CHARS:
        start += 1
    while end > start and text[end - 1] in EDGE_TRIM_CHARS:
        end -= 1
    # Remove a list bullet without removing a clinical minus sign in a value.
    if start < end and text[start] == "-" and (start + 1 == end or text[start + 1].isspace()):
        start += 1
        while start < end and text[start].isspace():
            start += 1
    return start, end


def clause_ranges(record: dict) -> list[tuple[int, int]]:
    """Return relation-safe, non-overlapping source ranges for simple targets."""
    text = record["text"]
    protected = _protected_intervals(record)
    coarse_cuts: list[tuple[int, int]] = []
    for match in SEPARATOR_PATTERN.finditer(text):
        if _cut_is_protected(match.start(), match.end(), protected):
            continue
        coarse_cuts.append((match.start(), match.end()))

    # Connector splitting is deliberately more conservative than punctuation:
    # both sides must contain an annotated clinical entity within the surrounding
    # coarse clause. This avoids turning ordinary prose into many empty fragments.
    coarse_boundaries = [0]
    coarse_boundaries.extend(end for _, end in coarse_cuts)
    coarse_boundaries.append(len(text))
    connector_cuts: list[tuple[int, int]] = []
    for match in CONNECTOR_PATTERN.finditer(text):
        if _cut_is_protected(match.start(), match.end(), protected):
            continue
        left_boundary = max(
            (end for _, end in coarse_cuts if end <= match.start()),
            default=0,
        )
        right_boundary = min(
            (start for start, _ in coarse_cuts if start >= match.end()),
            default=len(text),
        )
        if _has_entity_on_each_side(
            record,
            match.start(),
            match.end(),
            left_boundary,
            right_boundary,
        ):
            connector_cuts.append((match.start(), match.end()))

    cuts = sorted(set(coarse_cuts + connector_cuts))
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for start, end in cuts:
        if start < cursor:
            continue
        trimmed = _trim_range(text, cursor, start)
        if trimmed[0] < trimmed[1]:
            ranges.append(trimmed)
        cursor = end
    trimmed = _trim_range(text, cursor, len(text))
    if trimmed[0] < trimmed[1]:
        ranges.append(trimmed)

    if not ranges and text.strip():
        start = len(text) - len(text.lstrip())
        end = len(text.rstrip())
        ranges = [(start, end)]
    # A fragment ending in ':' is context for the following fact, not an atomic
    # sentence by itself. Merge it forward even when the header itself was
    # recognized as a TEST (for example ``Mạch:`` without an adjacent value).
    merged: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(ranges):
        start, end = ranges[cursor]
        fragment = text[start:end].strip()
        if fragment.endswith(":") and cursor + 1 < len(ranges):
            _, next_end = ranges[cursor + 1]
            merged.append((start, next_end))
            cursor += 2
        else:
            merged.append((start, end))
            cursor += 1
    ranges = merged
    return ranges


def _sentence_text(source_text: str) -> str:
    text = source_text.strip()
    if text and text[-1] not in ".!?:":
        text += "."
    return text


def _project_entity(entity: dict, *, source_start: int, sentence_index: int) -> dict:
    projected = deepcopy(entity)
    source_id = str(entity["id"])
    projected["id"] = f"S{sentence_index:03d}_{source_id}"
    projected["source_entity_id"] = source_id
    projected["source_start"] = int(entity["start"])
    projected["source_end"] = int(entity["end"])
    projected["start"] = int(entity["start"]) - source_start
    projected["end"] = int(entity["end"]) - source_start
    projected["source"] = f"{entity.get('source', 'unknown')}_projected"
    return projected


def _project_relations(
    record: dict,
    entity_id_map: dict[str, str],
    *,
    sentence_index: int,
) -> list[dict]:
    projected: list[dict] = []
    for relation in record.get("relations", []):
        subject = relation.get("subject")
        obj = relation.get("object")
        if obj not in entity_id_map:
            continue
        if subject == record.get("doc_id"):
            projected_subject = subject
        elif subject in entity_id_map:
            projected_subject = entity_id_map[subject]
        else:
            continue
        copied = deepcopy(relation)
        copied["source_relation_id"] = relation.get("id")
        copied["subject"] = projected_subject
        copied["object"] = entity_id_map[obj]
        copied["id"] = f"S{sentence_index:03d}_{relation.get('id', len(projected) + 1)}"
        if relation.get("source") == "rule":
            copied["source"] = "rule_projected"
        projected.append(copied)
    return projected


def decompose_record(record: dict) -> tuple[dict, list[dict]]:
    """Create one seq2seq annotation and sentence-level joint records."""
    text = record["text"]
    ranges = clause_ranges(record)
    simple_records: list[dict] = []
    sentence_summaries: list[dict] = []

    for sentence_index, (source_start, source_end) in enumerate(ranges, start=1):
        source_slice = text[source_start:source_end]
        sentence_text = _sentence_text(source_slice)
        source_entities = [
            entity
            for entity in record.get("entities", [])
            if source_start <= int(entity["start"])
            and int(entity["end"]) <= source_end
        ]
        projected_entities = [
            _project_entity(
                entity,
                source_start=source_start,
                sentence_index=sentence_index,
            )
            for entity in source_entities
        ]
        entity_id_map = {
            entity["source_entity_id"]: entity["id"]
            for entity in projected_entities
        }
        projected_relations = _project_relations(
            record,
            entity_id_map,
            sentence_index=sentence_index,
        )
        simple_id = f"{record['segment_id']}__S{sentence_index:03d}"
        simple_hash = _stable_hash(
            record.get("doc_id"),
            record.get("segment_id"),
            source_start,
            source_end,
            sentence_text,
        )
        simple_record = {
            "segment_id": simple_id,
            "source_segment_id": record["segment_id"],
            "doc_id": record["doc_id"],
            "disease_labels": list(record.get("disease_labels", [])),
            "section": record.get("section"),
            "text": sentence_text,
            "source_text": source_slice,
            "source_start": source_start,
            "source_end": source_end,
            "section_start": int(record.get("section_start", 0)) + source_start,
            "section_end": int(record.get("section_start", 0)) + source_end,
            "doc_start": int(record.get("doc_start", 0)) + source_start,
            "doc_end": int(record.get("doc_start", 0)) + source_end,
            "segment_hash": simple_hash,
            "source_segment_hash": record.get("segment_hash"),
            "annotation_status": "SILVER_SIMPLE_V1_3",
            "training_eligible": True,
            "gold_policy": record.get(
                "gold_policy",
                "silver_accepted_as_gold_by_project_owner",
            ),
            "simplification_method": ANNOTATION_METHOD,
            "entities": projected_entities,
            "relations": projected_relations,
            "relation_candidates": [],
            "needs_review": False,
            "review_notes": "",
        }
        simple_records.append(simple_record)
        sentence_summaries.append({
            "simple_id": simple_id,
            "text": sentence_text,
            "source_start": source_start,
            "source_end": source_end,
            "source_entity_ids": [entity["id"] for entity in source_entities],
            "source_relation_ids": [
                relation.get("source_relation_id")
                for relation in projected_relations
                if str(relation.get("predicate", "")).casefold() in LEARNED_RELATIONS
            ],
        })

    target_text = " ".join(
        f"{SENTENCE_OPEN} {item['text']} {SENTENCE_CLOSE}"
        for item in sentence_summaries
    )
    source_entity_ids = {
        str(entity["id"])
        for entity in record.get("entities", [])
    }
    projected_entity_ids = {
        entity["source_entity_id"]
        for simple in simple_records
        for entity in simple["entities"]
    }
    source_relation_ids = {
        str(relation.get("id"))
        for relation in _learned_relations(record)
    }
    projected_relation_ids = {
        str(relation.get("source_relation_id"))
        for simple in simple_records
        for relation in simple["relations"]
        if str(relation.get("predicate", "")).casefold() in LEARNED_RELATIONS
    }
    source_entities_by_id = {
        str(entity["id"]): entity
        for entity in record.get("entities", [])
    }
    required_relations = []
    for relation in _learned_relations(record):
        head = source_entities_by_id.get(str(relation.get("subject")))
        tail = source_entities_by_id.get(str(relation.get("object")))
        if not head or not tail:
            continue
        required_relations.append({
            "id": relation.get("id"),
            "head_text": head["text"],
            "predicate": relation["predicate"],
            "tail_text": tail["text"],
        })
    negation_cues = [
        match.group(0)
        for match in re.finditer(
            r"(?<!\w)(?:không\s+ghi\s+nhận|chưa\s+ghi\s+nhận|không\s+thấy|"
            r"không\s+có|không\s+rõ|không|chưa)(?!\w)",
            text,
            re.IGNORECASE,
        )
    ]
    numeric_values = [
        match.group(0)
        for match in re.finditer(r"(?<!\w)\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?", text)
    ]
    qualitative_values = [
        match.group(1)
        for match in re.finditer(
            r"[:=]\s*(\+{1,4}|-{1,4}|NEG|NORM|HI|LOW)(?=\s*[,;.]|\s|$)",
            text,
            re.IGNORECASE,
        )
    ]
    unbalanced_source_delimiters = any(
        text.count(opener) != text.count(closer)
        for opener, closer in (("(", ")"), ("[", "]"), ("{", "}"))
    )
    warnings = []
    if unbalanced_source_delimiters:
        warnings.append("unbalanced_delimiters_in_source")
    if any(item["text"].rstrip().endswith(":") for item in sentence_summaries):
        warnings.append("incomplete_trailing_colon_fragment")
    pair = {
        "pair_id": record["segment_id"],
        "doc_id": record["doc_id"],
        "disease_labels": list(record.get("disease_labels", [])),
        "section": record.get("section"),
        "source_segment_hash": record.get("segment_hash"),
        "source_text": text,
        "target_text": target_text,
        "sentences": sentence_summaries,
        "required_entities": [
            {
                "id": entity["id"],
                "text": entity["text"],
                "label": entity["label"],
            }
            for entity in record.get("entities", [])
        ],
        "required_relations": required_relations,
        "preservation_items": {
            "negation_cues": negation_cues,
            "numeric_values": numeric_values,
            "qualitative_values": qualitative_values,
        },
        "annotation_status": "SILVER_SIMPLE_V1_2",
        "annotation_method": ANNOTATION_METHOD,
        "needs_review": bool(warnings),
        "warnings": warnings,
        "quality": {
            "source_entities": len(source_entity_ids),
            "projected_entities": len(projected_entity_ids),
            "entity_coverage": (
                len(projected_entity_ids) / len(source_entity_ids)
                if source_entity_ids
                else 1.0
            ),
            "source_learned_relations": len(source_relation_ids),
            "projected_learned_relations": len(projected_relation_ids),
            "relation_coverage": (
                len(projected_relation_ids) / len(source_relation_ids)
                if source_relation_ids
                else 1.0
            ),
            "missing_entity_ids": sorted(source_entity_ids - projected_entity_ids),
            "missing_relation_ids": sorted(source_relation_ids - projected_relation_ids),
        },
    }
    return pair, simple_records


def seq2seq_row(pair: dict) -> dict:
    return {
        "id": pair["pair_id"],
        "doc_id": pair["doc_id"],
        "input_text": pair["source_text"],
        "target_text": pair["target_text"],
    }


def audit_simplification(
    pairs: Iterable[dict],
    simple_records: Iterable[dict],
) -> dict:
    pairs = list(pairs)
    simple_records = list(simple_records)
    status_counts = Counter(pair.get("annotation_status", "UNKNOWN") for pair in pairs)
    entity_missing = sum(
        len(pair.get("quality", {}).get("missing_entity_ids", []))
        for pair in pairs
    )
    relation_missing = sum(
        len(pair.get("quality", {}).get("missing_relation_ids", []))
        for pair in pairs
    )
    source_entities = sum(
        int(pair.get("quality", {}).get("source_entities", 0))
        for pair in pairs
    )
    projected_entities = sum(
        int(pair.get("quality", {}).get("projected_entities", 0))
        for pair in pairs
    )
    source_relations = sum(
        int(pair.get("quality", {}).get("source_learned_relations", 0))
        for pair in pairs
    )
    projected_relations = sum(
        int(pair.get("quality", {}).get("projected_learned_relations", 0))
        for pair in pairs
    )
    sentence_lengths = [len(record.get("text", "")) for record in simple_records]
    warning_counts = Counter(
        warning
        for pair in pairs
        for warning in pair.get("warnings", [])
    )
    negation_total = negation_kept = 0
    numeric_total = numeric_kept = 0
    qualitative_total = qualitative_kept = 0
    for pair in pairs:
        target = _normalized_text(pair.get("target_text", ""))
        for cue in pair.get("preservation_items", {}).get("negation_cues", []):
            negation_total += 1
            negation_kept += _normalized_text(cue) in target
        for value in pair.get("preservation_items", {}).get("numeric_values", []):
            numeric_total += 1
            numeric_kept += _normalized_text(value) in target
        for value in pair.get("preservation_items", {}).get("qualitative_values", []):
            qualitative_total += 1
            qualitative_kept += _normalized_text(value) in target
    return {
        "annotation_method": ANNOTATION_METHOD,
        "pairs": len(pairs),
        "simple_sentences": len(simple_records),
        "sentences_per_pair": (
            len(simple_records) / len(pairs) if pairs else 0.0
        ),
        "status_counts": dict(status_counts.most_common()),
        "pairs_needing_review": sum(bool(pair.get("needs_review")) for pair in pairs),
        "warning_counts": dict(warning_counts.most_common()),
        "source_entities": source_entities,
        "projected_entities": projected_entities,
        "entity_coverage": (
            projected_entities / source_entities if source_entities else 1.0
        ),
        "missing_entities": entity_missing,
        "source_learned_relations": source_relations,
        "projected_learned_relations": projected_relations,
        "relation_coverage": (
            projected_relations / source_relations if source_relations else 1.0
        ),
        "missing_learned_relations": relation_missing,
        "negation_items": negation_total,
        "negation_preservation": (
            negation_kept / negation_total if negation_total else 1.0
        ),
        "numeric_items": numeric_total,
        "numeric_preservation": (
            numeric_kept / numeric_total if numeric_total else 1.0
        ),
        "qualitative_items": qualitative_total,
        "qualitative_preservation": (
            qualitative_kept / qualitative_total if qualitative_total else 1.0
        ),
        "max_sentence_chars": max(sentence_lengths, default=0),
        "mean_sentence_chars": (
            sum(sentence_lengths) / len(sentence_lengths)
            if sentence_lengths
            else 0.0
        ),
    }
