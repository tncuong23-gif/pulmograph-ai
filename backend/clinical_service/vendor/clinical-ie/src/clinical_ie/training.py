from __future__ import annotations

import hashlib
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


ENTITY_LABELS = (
    "symptom",
    "sign",
    "condition",
    "test",
    "result",
    "anatomy",
    "treatment",
    "time",
)

LEGACY_LEARNED_RELATIONS = (
    "has_result",
    "located_at",
    "occurs_at",
    "treated_with",
)

LEARNED_RELATIONS = (
    "has_result",
    "reveals",
    "located_at",
    "has_duration",
    "onset_at",
    "has_frequency",
    "occurs_at",
    "treated_with",
    "not_improved_by",
)


def relation_labels_from_metrics(metrics: dict) -> tuple[str, ...]:
    """Read a run's label vocabulary without breaking pre-v1.3 checkpoints."""
    labels = metrics.get("relation_labels")
    if not isinstance(labels, list) or not labels:
        return LEGACY_LEARNED_RELATIONS
    normalized = tuple(str(label).casefold() for label in labels)
    unknown = sorted(set(normalized) - set(LEARNED_RELATIONS))
    if unknown:
        raise ValueError(f"Unknown relation labels in metrics.json: {unknown}")
    return normalized

# Keep punctuation as independent tokens. Clinical text frequently joins otherwise
# unrelated concepts with '/', '-', '#', or '+'. Treating those characters as part
# of a word can make a valid entity begin in the middle of a token (for example,
# "trái/Lao phổi"). Splitting punctuation also preserves every annotated boundary.
TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def promote_proxy_gold(records: Iterable[dict]) -> list[dict]:
    promoted: list[dict] = []
    seen_hashes: set[str] = set()
    for source in records:
        segment_hash = source.get("segment_hash")
        if not segment_hash:
            raise ValueError(f"Missing segment_hash: {source.get('segment_id')}")
        if segment_hash in seen_hashes:
            raise ValueError(f"Duplicate segment_hash in proxy gold: {segment_hash}")
        seen_hashes.add(segment_hash)

        record = dict(source)
        record["source_annotation_status"] = source.get("annotation_status", "UNKNOWN")
        record["source_needs_review"] = bool(source.get("needs_review"))
        record["annotation_status"] = "PROXY_GOLD"
        record["needs_review"] = False
        record["training_eligible"] = True
        record["gold_policy"] = "silver_accepted_as_gold_by_project_owner"
        promoted.append(record)
    return promoted


def _allocate_counts(total: int, ratios: dict[str, float]) -> dict[str, int]:
    raw = {name: total * ratio for name, ratio in ratios.items()}
    allocated = {name: math.floor(value) for name, value in raw.items()}
    remainder = total - sum(allocated.values())
    order = sorted(ratios, key=lambda name: (-(raw[name] - allocated[name]), name))
    for name in order[:remainder]:
        allocated[name] += 1
    return allocated


def grouped_stratified_split(
    records: list[dict],
    *,
    train_ratio: float = 0.80,
    dev_ratio: float = 0.10,
    test_ratio: float = 0.10,
    seed: int = 42,
) -> dict[str, list[dict]]:
    ratios = {"train": train_ratio, "dev": dev_ratio, "test": test_ratio}
    if not math.isclose(sum(ratios.values()), 1.0, abs_tol=1e-9):
        raise ValueError(f"Split ratios must sum to 1.0: {ratios}")

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_doc[record["doc_id"]].append(record)

    relation_counts = Counter(
        relation["predicate"]
        for record in records
        for relation in record.get("relations", [])
        if relation["predicate"].casefold() in LEARNED_RELATIONS
    )
    rare_relations = {
        predicate
        for predicate, count in relation_counts.items()
        if count < 100
    }

    by_disease: dict[str, list[list[dict]]] = defaultdict(list)
    for group in by_doc.values():
        diseases = {
            disease
            for record in group
            for disease in record.get("disease_labels", [])
        }
        disease_key = "+".join(sorted(diseases)) if diseases else "UNKNOWN"
        group_relations = {
            relation["predicate"]
            for record in group
            for relation in record.get("relations", [])
        }
        rare_signature = sorted(group_relations & rare_relations)
        # Rare learned relations take priority as a stratum so that dev/test do
        # not accidentally contain too few positives to measure. All remaining
        # documents keep the disease-level stratification used for classification.
        stratum = (
            f"RARE:{'+'.join(rare_signature)}"
            if rare_signature
            else f"DISEASE:{disease_key}"
        )
        by_disease[stratum].append(group)

    rng = random.Random(seed)
    splits: dict[str, list[dict]] = {name: [] for name in ratios}
    for disease in sorted(by_disease):
        groups = by_disease[disease]
        rng.shuffle(groups)
        groups.sort(key=len, reverse=True)
        total = sum(len(group) for group in groups)
        targets = _allocate_counts(total, ratios)
        assigned = {name: 0 for name in ratios}

        for group in groups:
            split_order = list(ratios)
            rng.shuffle(split_order)
            split_name = max(
                split_order,
                key=lambda name: (
                    targets[name] - assigned[name],
                    -assigned[name],
                ),
            )
            splits[split_name].extend(group)
            assigned[split_name] += len(group)

    for split_name, split_records in splits.items():
        rng.shuffle(split_records)
        splits[split_name] = split_records
    assert_no_split_leakage(splits)
    return splits


def assert_no_split_leakage(splits: dict[str, list[dict]]) -> None:
    names = sorted(splits)
    for index, left_name in enumerate(names):
        left_docs = {record["doc_id"] for record in splits[left_name]}
        left_hashes = {record["segment_hash"] for record in splits[left_name]}
        for right_name in names[index + 1:]:
            right_docs = {record["doc_id"] for record in splits[right_name]}
            right_hashes = {record["segment_hash"] for record in splits[right_name]}
            shared_docs = left_docs & right_docs
            shared_hashes = left_hashes & right_hashes
            if shared_docs:
                raise ValueError(
                    f"Document leakage between {left_name}/{right_name}: {sorted(shared_docs)[:5]}"
                )
            if shared_hashes:
                raise ValueError(
                    f"Segment leakage between {left_name}/{right_name}: {sorted(shared_hashes)[:5]}"
                )


def oversample_rare_relation_records(
    records: list[dict],
    *,
    minimum_relations: int = 120,
    seed: int = 42,
) -> list[dict]:
    """Repeat train-only records until every observed learned relation reaches a floor."""
    if minimum_relations < 1:
        raise ValueError("minimum_relations must be positive")

    rng = random.Random(seed)
    balanced = list(records)
    relation_counts = Counter(
        relation["predicate"].casefold()
        for record in balanced
        for relation in record.get("relations", [])
        if relation["predicate"].casefold() in LEARNED_RELATIONS
    )

    for predicate in LEARNED_RELATIONS:
        if relation_counts[predicate] == 0 or relation_counts[predicate] >= minimum_relations:
            continue
        candidates = [
            record
            for record in records
            if any(
                relation["predicate"].casefold() == predicate
                for relation in record.get("relations", [])
            )
        ]
        rng.shuffle(candidates)
        cursor = 0
        while relation_counts[predicate] < minimum_relations:
            record = candidates[cursor % len(candidates)]
            balanced.append(record)
            relation_counts.update(
                relation["predicate"].casefold()
                for relation in record.get("relations", [])
                if relation["predicate"].casefold() in LEARNED_RELATIONS
            )
            cursor += 1

    rng.shuffle(balanced)
    return balanced


def tokenize_with_offsets(
    text: str,
    *,
    entity_boundaries: Iterable[int] = (),
) -> tuple[list[str], list[tuple[int, int]]]:
    """Tokenize text while guaranteeing that annotated spans align to tokens.

    A small amount of accepted silver data contains partial clinical shorthand such
    as ``26l/p`` inside ``26l/phút``. Keeping the annotated boundary is preferable
    to silently changing proxy-gold labels, so a word token is split at any entity
    boundary that falls inside it.
    """
    boundaries = sorted({point for point in entity_boundaries if 0 < point < len(text)})
    tokens: list[str] = []
    offsets: list[tuple[int, int]] = []
    for match in TOKEN_PATTERN.finditer(text):
        cuts = [
            point
            for point in boundaries
            if match.start() < point < match.end()
        ]
        starts = [match.start(), *cuts]
        ends = [*cuts, match.end()]
        for start, end in zip(starts, ends):
            tokens.append(text[start:end])
            offsets.append((start, end))
    return tokens, offsets


def _entity_token_span(entity: dict, offsets: list[tuple[int, int]]) -> tuple[int, int]:
    covered = [
        index
        for index, (start, end) in enumerate(offsets)
        if start < entity["end"] and entity["start"] < end
    ]
    if not covered:
        raise ValueError(f"Entity has no tokens: {entity}")
    token_start, token_end = covered[0], covered[-1]
    if offsets[token_start][0] != entity["start"] or offsets[token_end][1] != entity["end"]:
        raise ValueError(
            "Entity boundary does not align with token boundaries: "
            f"{entity['id']}:{entity['text']}:{entity['start']}:{entity['end']}"
        )
    return token_start, token_end


def to_gliner_record(record: dict, *, include_relations: bool) -> dict:
    ordered_entities = sorted(
        record.get("entities", []),
        key=lambda entity: (entity["start"], entity["end"], entity["id"]),
    )
    entity_boundaries = {
        point
        for entity in ordered_entities
        for point in (entity["start"], entity["end"])
    }
    tokens, offsets = tokenize_with_offsets(
        record["text"],
        entity_boundaries=entity_boundaries,
    )
    ner: list[list[int | str]] = []
    entity_index: dict[str, int] = {}
    for index, entity in enumerate(ordered_entities):
        token_start, token_end = _entity_token_span(entity, offsets)
        ner.append([token_start, token_end, entity["label"].casefold()])
        entity_index[entity["id"]] = index

    converted: dict = {
        "tokenized_text": tokens,
        "ner": ner,
        "ner_labels": list(ENTITY_LABELS),
    }
    if include_relations:
        relations: list[list[int | str]] = []
        for relation in record.get("relations", []):
            predicate = relation["predicate"].casefold()
            if predicate not in LEARNED_RELATIONS:
                continue
            subject = relation["subject"]
            obj = relation["object"]
            if subject not in entity_index or obj not in entity_index:
                raise ValueError(
                    f"Learned relation endpoint is not an entity: {record['segment_id']}:{relation}"
                )
            relations.append([entity_index[subject], entity_index[obj], predicate])
        converted["relations"] = relations
        converted["rel_labels"] = list(LEARNED_RELATIONS)
    return converted


def conversion_index(records: list[dict]) -> list[dict]:
    occurrences: Counter[str] = Counter()
    output: list[dict] = []
    for index, record in enumerate(records):
        occurrences[record["segment_id"]] += 1
        output.append({
            "row": index,
            "sample_instance_id": (
                f"{record['segment_id']}#{occurrences[record['segment_id']]}"
            ),
            "segment_id": record["segment_id"],
            "doc_id": record["doc_id"],
            "segment_hash": record["segment_hash"],
            "disease_labels": record.get("disease_labels", []),
            "section": record.get("section"),
        })
    return output


def summarize_records(records: Iterable[dict]) -> dict:
    records = list(records)
    disease_counts: Counter[str] = Counter()
    section_counts: Counter[str] = Counter()
    entity_counts: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()
    doc_ids: set[str] = set()
    for record in records:
        doc_ids.add(record["doc_id"])
        disease_counts.update(record.get("disease_labels", []))
        section_counts[record.get("section", "UNKNOWN")] += 1
        entity_counts.update(entity["label"] for entity in record.get("entities", []))
        relation_counts.update(
            relation["predicate"]
            for relation in record.get("relations", [])
            if str(relation.get("source", "")).startswith("rule")
            and str(relation.get("predicate", "")).casefold() in LEARNED_RELATIONS
        )
    return {
        "records": len(records),
        "documents": len(doc_ids),
        "disease_counts": dict(disease_counts.most_common()),
        "section_counts": dict(section_counts.most_common()),
        "entity_counts": dict(entity_counts.most_common()),
        "learned_relation_counts": dict(relation_counts.most_common()),
    }
