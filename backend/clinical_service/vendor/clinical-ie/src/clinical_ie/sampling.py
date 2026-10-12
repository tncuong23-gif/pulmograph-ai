from __future__ import annotations

import hashlib
import random
import re
from collections import Counter, defaultdict
from typing import Iterable

from .preprocess import canonical_content, iter_segments
from .rules import preannotate_segment


def _segment_hash(text: str) -> str:
    return hashlib.sha256(canonical_content(text).encode("utf-8")).hexdigest()


def _allocate(total: int, keys: list[str]) -> dict[str, int]:
    if not keys:
        return {}
    base, remainder = divmod(total, len(keys))
    return {key: base + (1 if index < remainder else 0) for index, key in enumerate(keys)}


def _priority(record: dict) -> tuple[int, int, int, float]:
    labels = {entity["label"] for entity in record["entities"]}
    learned_relations = sum(1 for relation in record["relations"] if relation["source"] == "rule")
    low_confidence = sum(1 for entity in record["entities"] if entity["confidence"] < 0.80)
    return (len(labels), learned_relations, len(record["entities"]), -low_confidence)


def build_candidate_pool(documents: Iterable[dict]) -> list[dict]:
    deduplicated: dict[str, dict] = {}
    for document in documents:
        for segment in iter_segments(document):
            if len(segment["text"].strip()) < 20:
                continue
            annotated = preannotate_segment(segment)
            content_hash = _segment_hash(segment["text"])
            annotated["segment_hash"] = content_hash
            previous = deduplicated.get(content_hash)
            if previous is None or _priority(annotated) > _priority(previous):
                deduplicated[content_hash] = annotated
    return list(deduplicated.values())


def sample_pilot(
    candidates: list[dict],
    *,
    size: int,
    negative_ratio: float = 0.20,
    seed: int = 42,
) -> list[dict]:
    rng = random.Random(seed)
    by_disease: dict[str, list[dict]] = defaultdict(list)
    for record in candidates:
        disease = record["disease_labels"][0] if record["disease_labels"] else "UNKNOWN"
        by_disease[disease].append(record)

    diseases = sorted(by_disease)
    quotas = _allocate(min(size, len(candidates)), diseases)
    selected: list[dict] = []
    selected_hashes: set[str] = set()

    for disease in diseases:
        group = by_disease[disease]
        by_section: dict[str, list[dict]] = defaultdict(list)
        for record in group:
            by_section[record["section"]].append(record)

        quota = quotas[disease]
        section_quotas = _allocate(quota, sorted(by_section))
        chosen: list[dict] = []
        for section in sorted(by_section):
            section_group = by_section[section]
            positives = [record for record in section_group if record["entities"]]
            negatives = [record for record in section_group if not record["entities"]]
            rng.shuffle(positives)
            rng.shuffle(negatives)
            positives.sort(key=_priority, reverse=True)

            section_quota = section_quotas[section]
            negative_target = round(section_quota * negative_ratio)
            positive_target = section_quota - negative_target
            section_chosen = positives[:positive_target] + negatives[:negative_target]
            if len(section_chosen) < section_quota:
                section_ids = {id(record) for record in section_chosen}
                remaining = [record for record in section_group if id(record) not in section_ids]
                rng.shuffle(remaining)
                section_chosen.extend(remaining[: section_quota - len(section_chosen)])
            chosen.extend(section_chosen)

        if len(chosen) < quota:
            chosen_ids = {id(record) for record in chosen}
            remaining = [record for record in group if id(record) not in chosen_ids]
            rng.shuffle(remaining)
            remaining.sort(key=_priority, reverse=True)
            chosen.extend(remaining[: quota - len(chosen)])
        for record in chosen:
            if record["segment_hash"] not in selected_hashes:
                selected.append(record)
                selected_hashes.add(record["segment_hash"])

    if len(selected) < size:
        remaining = [record for record in candidates if record["segment_hash"] not in selected_hashes]
        rng.shuffle(remaining)
        remaining.sort(key=_priority, reverse=True)
        selected.extend(remaining[: size - len(selected)])

    rng.shuffle(selected)
    return selected[:size]


def choose_seed(pilot: list[dict], size: int, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    by_stratum: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in pilot:
        if not record["entities"]:
            continue
        disease = record["disease_labels"][0] if record["disease_labels"] else "UNKNOWN"
        by_stratum[(disease, record["section"])].append(record)
    for records in by_stratum.values():
        rng.shuffle(records)
        records.sort(key=_priority, reverse=True)

    selected: list[dict] = []
    strata = sorted(by_stratum)
    while strata and len(selected) < size:
        next_round: list[tuple[str, str]] = []
        for stratum in strata:
            if by_stratum[stratum] and len(selected) < size:
                selected.append(by_stratum[stratum].pop(0))
            if by_stratum[stratum]:
                next_round.append(stratum)
        strata = next_round
    return selected


def sampling_report(pilot: Iterable[dict]) -> dict:
    disease_counts: Counter[str] = Counter()
    section_counts: Counter[str] = Counter()
    entity_counts: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()
    positive = 0
    needs_review = 0
    total = 0
    for record in pilot:
        total += 1
        disease_counts.update(record.get("disease_labels", []))
        section_counts[record["section"]] += 1
        entity_counts.update(entity["label"] for entity in record["entities"])
        relation_counts.update(relation["predicate"] for relation in record["relations"])
        positive += bool(record["entities"])
        needs_review += bool(record.get("needs_review"))
    return {
        "segments": total,
        "positive_segments": positive,
        "negative_segments": total - positive,
        "needs_review": needs_review,
        "disease_counts": dict(disease_counts.most_common()),
        "section_counts": dict(section_counts.most_common()),
        "entity_counts": dict(entity_counts.most_common()),
        "relation_counts": dict(relation_counts.most_common()),
    }
