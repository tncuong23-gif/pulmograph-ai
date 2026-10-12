from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from .schema import ClinicalSchema


def validate_annotation(record: dict, schema: ClinicalSchema) -> list[str]:
    errors: list[str] = []
    text = record.get("text", "")
    entities = record.get("entities", [])
    relations = record.get("relations", [])
    entity_by_id: dict[str, dict] = {}

    for entity in entities:
        entity_id = entity.get("id")
        if not entity_id or entity_id in entity_by_id:
            errors.append(f"duplicate_or_missing_entity_id:{entity_id}")
            continue
        entity_by_id[entity_id] = entity
        label = entity.get("label")
        if label not in schema.entity_types:
            errors.append(f"invalid_entity_label:{entity_id}:{label}")
        start, end = entity.get("start"), entity.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(text)):
            errors.append(f"invalid_entity_offset:{entity_id}:{start}:{end}")
        elif text[start:end] != entity.get("text"):
            errors.append(f"entity_text_mismatch:{entity_id}")

        for attribute, value in entity.get("qualifiers", {}).items():
            allowed = schema.attribute_values(attribute)
            if not allowed:
                errors.append(f"unknown_attribute:{entity_id}:{attribute}")
            elif value not in allowed:
                errors.append(f"invalid_attribute_value:{entity_id}:{attribute}:{value}")

    ordered = sorted(entities, key=lambda item: (item.get("start", -1), item.get("end", -1)))
    for left, right in zip(ordered, ordered[1:]):
        if left.get("end", -1) > right.get("start", -1):
            errors.append(f"overlapping_entities:{left.get('id')}:{right.get('id')}")

    relation_ids: set[str] = set()
    for relation in relations:
        relation_id = relation.get("id")
        if not relation_id or relation_id in relation_ids:
            errors.append(f"duplicate_or_missing_relation_id:{relation_id}")
        relation_ids.add(relation_id)
        predicate = relation.get("predicate")
        if predicate not in schema.relation_types:
            errors.append(f"invalid_relation_label:{relation_id}:{predicate}")
            continue

        subject_id = relation.get("subject")
        object_id = relation.get("object")
        if subject_id == record.get("doc_id"):
            subject_type = "CASE"
        elif subject_id in entity_by_id:
            subject_type = entity_by_id[subject_id].get("label")
        else:
            errors.append(f"missing_relation_subject:{relation_id}:{subject_id}")
            continue
        if object_id not in entity_by_id:
            errors.append(f"missing_relation_object:{relation_id}:{object_id}")
            continue
        object_type = entity_by_id[object_id].get("label")

        if subject_type not in schema.allowed_subjects(predicate):
            errors.append(f"invalid_relation_subject_type:{relation_id}:{subject_type}")
        if object_type not in schema.allowed_objects(predicate):
            errors.append(f"invalid_relation_object_type:{relation_id}:{object_type}")

    return errors


def validate_records(records: Iterable[dict], schema: ClinicalSchema) -> dict:
    error_counts: Counter[str] = Counter()
    invalid_records = 0
    total = 0
    examples: list[dict] = []
    for record in records:
        total += 1
        errors = validate_annotation(record, schema)
        if errors:
            invalid_records += 1
            error_counts.update(error.split(":", 1)[0] for error in errors)
            if len(examples) < 20:
                examples.append({"segment_id": record.get("segment_id"), "errors": errors})
    return {
        "records": total,
        "invalid_records": invalid_records,
        "valid_records": total - invalid_records,
        "error_counts": dict(error_counts.most_common()),
        "examples": examples,
    }


def read_jsonl(path: str | Path) -> Iterable[dict]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc

