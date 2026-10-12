from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .inference import RELATION_SIGNATURES, relation_is_compatible, resolve_device
from .rules import CASE_RELATIONS, infer_qualifiers
from .simplification import (
    GENERATED_SENTENCE_PATTERN,
    LEGACY_GENERATED_SENTENCE_PATTERN,
    parse_generated_simple_sentences,
)
from .training import (
    ENTITY_LABELS,
    LEGACY_LEARNED_RELATIONS,
    LEARNED_RELATIONS,
    relation_labels_from_metrics,
)


SIMPLIFIER_TASK = "clinical_complex_to_simple"
SIMPLE_JOINT_TASK = "joint_ner_relex_simple_sentence"
INPUT_PREFIX = "simplify_vi_clinical: "


@dataclass(frozen=True)
class SimplifierRun:
    run_dir: Path
    final_model_dir: Path
    metrics_path: Path
    metrics: dict
    run_config: dict
    weight_path: Path


@dataclass(frozen=True)
class SimpleJointRun:
    run_dir: Path
    final_model_dir: Path
    metrics_path: Path
    metrics: dict
    entity_threshold: float
    relation_threshold: float
    weight_path: Path
    relation_labels: tuple[str, ...] = LEGACY_LEARNED_RELATIONS


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON phải là object: {path}")
    return value


def _select_run(
    models_root: str | Path,
    model_run: str | Path | None,
    *,
    task: str,
) -> Path:
    if model_run is not None:
        requested = Path(model_run).expanduser().resolve()
        candidates = [requested.parent if requested.name == "final_model" else requested]
    else:
        root = Path(models_root).expanduser().resolve()
        candidates = []
        if root.is_dir():
            for metrics_path in sorted(root.glob("*/metrics.json")):
                try:
                    metrics = _load_json(metrics_path)
                except (OSError, json.JSONDecodeError, ValueError):
                    continue
                if metrics.get("task") == task:
                    candidates.append(metrics_path.parent)
    if not candidates:
        raise FileNotFoundError(
            f"Không tìm thấy model task={task!r}. Hãy tải run Colab vào models/ "
            "hoặc truyền đường dẫn bằng CLI."
        )
    if len(candidates) > 1:
        raise ValueError(
            f"Có nhiều model task={task!r}; cần chỉ định rõ: "
            + ", ".join(str(path) for path in candidates)
        )
    return candidates[0]


def _weight_file(final_model_dir: Path) -> Path:
    for name in ("model.safetensors", "pytorch_model.bin"):
        path = final_model_dir / name
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"Thiếu model.safetensors hoặc pytorch_model.bin trong {final_model_dir}"
    )


def resolve_simplifier_run(
    models_root: str | Path,
    model_run: str | Path | None = None,
) -> SimplifierRun:
    run_dir = _select_run(models_root, model_run, task=SIMPLIFIER_TASK)
    metrics_path = run_dir / "metrics.json"
    config_path = run_dir / "run_config.json"
    final_model_dir = run_dir / "final_model"
    for path in (metrics_path, config_path, final_model_dir / "config.json"):
        if not path.is_file():
            raise FileNotFoundError(f"Simplifier run chưa đầy đủ: {path}")
    metrics = _load_json(metrics_path)
    run_config = _load_json(config_path)
    if metrics.get("task") != SIMPLIFIER_TASK:
        raise ValueError(f"Sai task trong {metrics_path}")
    if run_config.get("task") != SIMPLIFIER_TASK:
        raise ValueError(f"Sai task trong {config_path}")
    return SimplifierRun(
        run_dir=run_dir,
        final_model_dir=final_model_dir,
        metrics_path=metrics_path,
        metrics=metrics,
        run_config=run_config,
        weight_path=_weight_file(final_model_dir),
    )


def resolve_simple_joint_run(
    models_root: str | Path,
    model_run: str | Path | None = None,
) -> SimpleJointRun:
    run_dir = _select_run(models_root, model_run, task=SIMPLE_JOINT_TASK)
    metrics_path = run_dir / "metrics.json"
    final_model_dir = run_dir / "final_model"
    for path in (metrics_path, final_model_dir / "gliner_config.json"):
        if not path.is_file():
            raise FileNotFoundError(f"Simple-joint run chưa đầy đủ: {path}")
    metrics = _load_json(metrics_path)
    if metrics.get("task") != SIMPLE_JOINT_TASK:
        raise ValueError(f"Sai task trong {metrics_path}")
    entity_threshold = float(metrics["entity_threshold"])
    relation_threshold = float(metrics["best_dev_relation_threshold"])
    if not 0.0 <= entity_threshold <= 1.0:
        raise ValueError("entity_threshold nằm ngoài [0, 1]")
    if not 0.0 <= relation_threshold <= 1.0:
        raise ValueError("relation_threshold nằm ngoài [0, 1]")
    return SimpleJointRun(
        run_dir=run_dir,
        final_model_dir=final_model_dir,
        metrics_path=metrics_path,
        metrics=metrics,
        entity_threshold=entity_threshold,
        relation_threshold=relation_threshold,
        weight_path=_weight_file(final_model_dir),
        relation_labels=relation_labels_from_metrics(metrics),
    )


def model_status(
    models_root: str | Path,
    *,
    simplifier_run: str | Path | None = None,
    joint_run: str | Path | None = None,
) -> dict:
    simplifier = resolve_simplifier_run(models_root, simplifier_run)
    joint = resolve_simple_joint_run(models_root, joint_run)
    return {
        "status": "READY",
        "simplifier": {
            "run_dir": str(simplifier.run_dir),
            "weight_file": simplifier.weight_path.name,
            "weight_bytes": simplifier.weight_path.stat().st_size,
            "test_metrics": simplifier.metrics.get(
                "legacy_test", simplifier.metrics.get("test")
            ),
        },
        "simple_joint": {
            "run_dir": str(joint.run_dir),
            "weight_file": joint.weight_path.name,
            "weight_bytes": joint.weight_path.stat().st_size,
            "entity_threshold": joint.entity_threshold,
            "relation_threshold": joint.relation_threshold,
            "relation_labels": list(joint.relation_labels),
            "test_entity_micro": joint.metrics.get("test_entity_micro"),
            "test_relation_micro": joint.metrics.get("test_relation_micro"),
        },
    }


class ClinicalSimplifier:
    def __init__(
        self,
        model_run: SimplifierRun,
        *,
        device: str = "auto",
        batch_size: int = 4,
        num_beams: int = 4,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size phải lớn hơn 0")
        if num_beams < 1:
            raise ValueError("num_beams phải lớn hơn 0")
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as error:
            raise RuntimeError(
                "Thiếu dependency inference. Cài bằng: pip install -e '.[inference]'"
            ) from error
        self.torch = torch
        self.model_run = model_run
        self.device = resolve_device(device, torch)
        self.batch_size = batch_size
        self.num_beams = num_beams
        self.max_source_length = int(model_run.run_config.get("max_source_length", 512))
        self.max_target_length = int(model_run.run_config.get("max_target_length", 512))
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(model_run.final_model_dir), local_files_only=True
        )
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            str(model_run.final_model_dir), local_files_only=True
        )
        self.model.to(self.device)
        self.model.eval()

    def simplify(self, texts: list[str]) -> list[dict]:
        results: list[dict] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            encoded = self.tokenizer(
                [INPUT_PREFIX + text for text in batch],
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=self.max_source_length,
            ).to(self.device)
            with self.torch.inference_mode():
                generated = self.model.generate(
                    **encoded,
                    max_new_tokens=self.max_target_length,
                    num_beams=self.num_beams,
                    do_sample=False,
                    early_stopping=True,
                )
            decoded = self.tokenizer.batch_decode(generated, skip_special_tokens=False)
            for raw in decoded:
                cleaned = raw
                for token in (
                    self.tokenizer.pad_token or "",
                    self.tokenizer.eos_token or "",
                    self.tokenizer.bos_token or "",
                ):
                    if token:
                        cleaned = cleaned.replace(token, "")
                cleaned = cleaned.strip()
                sentences = parse_generated_simple_sentences(cleaned)
                strict_formats = []
                for pattern, open_pattern, close_pattern in (
                    (
                        GENERATED_SENTENCE_PATTERN,
                        r"<extra_id_0>",
                        r"<extra_id_1>",
                    ),
                    (
                        LEGACY_GENERATED_SENTENCE_PATTERN,
                        r"<SENT>",
                        r"</SENT>",
                    ),
                ):
                    open_tags = len(re.findall(open_pattern, cleaned, flags=re.IGNORECASE))
                    close_tags = len(re.findall(close_pattern, cleaned, flags=re.IGNORECASE))
                    residue = pattern.sub("", cleaned).strip()
                    strict_formats.append(
                        bool(sentences)
                        and open_tags == close_tags == len(sentences)
                        and open_tags > 0
                        and not residue
                    )
                tagged = any(strict_formats)
                results.append(
                    {
                        "raw_output": cleaned,
                        "sentences": sentences,
                        "tagged_parse": tagged,
                    }
                )
        return results


def _endpoint_index(endpoint: dict, predictions: list[dict]) -> int | None:
    index = endpoint.get("entity_idx")
    if isinstance(index, int) and 0 <= index < len(predictions):
        return index
    endpoint_label = str(endpoint.get("type", endpoint.get("label", ""))).casefold()
    for candidate_index, candidate in enumerate(predictions):
        if (
            candidate.get("start") == endpoint.get("start")
            and candidate.get("end") == endpoint.get("end")
            and str(candidate.get("label", "")).casefold() == endpoint_label
        ):
            return candidate_index
    return None


def _valid_relation(predicate: str, subject: dict, obj: dict) -> bool:
    signature = RELATION_SIGNATURES.get(predicate)
    if signature is None:
        return False
    allowed_subjects, allowed_objects = signature
    return subject["label"] in allowed_subjects and obj["label"] in allowed_objects


RELATION_CONTINUATION_PATTERN = re.compile(
    r"^\s*(?:có\s+)?(?:uống|dùng|xịt|tiêm|chích|truyền)\s+thuốc\b|"
    r"^\s*(?:có\s+)?điều\s+trị\s+tư\b",
    re.IGNORECASE,
)
RESPONSE_CUE_PATTERN = re.compile(
    r"(?:không|chưa)\s+(?:giảm|đỡ|cải\s+thiện|đáp\s+ứng)|"
    r"(?:có\s+đáp\s+ứng|cải\s+thiện|đỡ)",
    re.IGNORECASE,
)


def repair_relation_safe_sentences(sentences: list[str]) -> tuple[list[str], int]:
    """Merge a treatment-response continuation back with its clinical head."""
    repaired: list[str] = []
    repairs = 0
    for sentence in sentences:
        if (
            repaired
            and RELATION_CONTINUATION_PATTERN.search(sentence)
            and RESPONSE_CUE_PATTERN.search(sentence)
        ):
            left = repaired.pop().rstrip().rstrip(".!?:;")
            repaired.append(f"{left}, {sentence.lstrip()}")
            repairs += 1
        else:
            repaired.append(sentence)
    return repaired, repairs


def _all_occurrences(text: str, surface: str) -> list[tuple[int, int]]:
    if not surface:
        return []
    folded_text = text.casefold()
    folded_surface = surface.casefold()
    matches: list[tuple[int, int]] = []
    cursor = 0
    while True:
        start = folded_text.find(folded_surface, cursor)
        if start < 0:
            break
        matches.append((start, start + len(surface)))
        cursor = start + max(len(surface), 1)
    return matches


def _unique_surface_span(text: str, surface: str) -> tuple[int, int] | None:
    candidates = [surface.strip()]
    stripped_terminal = surface.strip().rstrip(".!?:")
    if stripped_terminal and stripped_terminal not in candidates:
        candidates.append(stripped_terminal)
    for candidate in candidates:
        matches = _all_occurrences(text, candidate)
        if len(matches) == 1:
            return matches[0]
    return None


class SimpleJointPipeline:
    """Run complex segment -> generated simple sentences -> joint NER/RelEx."""

    def __init__(
        self,
        simplifier_run: SimplifierRun,
        joint_run: SimpleJointRun,
        *,
        device: str = "auto",
        simplifier_batch_size: int = 4,
        joint_batch_size: int = 8,
        num_beams: int = 4,
    ) -> None:
        if joint_batch_size < 1:
            raise ValueError("joint_batch_size phải lớn hơn 0")
        self.simplifier = ClinicalSimplifier(
            simplifier_run,
            device=device,
            batch_size=simplifier_batch_size,
            num_beams=num_beams,
        )
        try:
            from gliner.model import UniEncoderTokenRelexGLiNER
        except ImportError as error:
            raise RuntimeError(
                "Thiếu dependency inference. Cài bằng: pip install -e '.[inference]'"
            ) from error
        self.joint_run = joint_run
        self.device = self.simplifier.device
        self.joint_batch_size = joint_batch_size
        self.joint_model = UniEncoderTokenRelexGLiNER.from_pretrained(
            str(joint_run.final_model_dir),
            local_files_only=True,
            map_location="cpu",
        )
        if self.joint_model.config.model_type != "gliner_uni_encoder_token_relex":
            raise RuntimeError(f"Sai kiến trúc model: {self.joint_model.config.model_type}")
        self.joint_model.to(self.device)
        self.joint_model.eval()

    def extract_segment(self, segment: dict) -> dict:
        return self.extract_segments([segment])[0]

    def extract_segments(self, segments: list[dict]) -> list[dict]:
        simplified = self.simplifier.simplify([segment["text"] for segment in segments])
        units: list[dict] = []
        for segment_index, (segment, generated) in enumerate(zip(segments, simplified)):
            repaired_sentences, repair_count = repair_relation_safe_sentences(
                generated["sentences"]
            )
            generated["sentences"] = repaired_sentences
            generated["relation_boundary_repairs"] = repair_count
            for sentence_index, sentence in enumerate(generated["sentences"], start=1):
                units.append(
                    {
                        "segment_index": segment_index,
                        "sentence_index": sentence_index,
                        "text": sentence,
                        "source_span": _unique_surface_span(segment["text"], sentence),
                    }
                )

        if units:
            with self.simplifier.torch.inference_mode():
                entity_batches, relation_batches = self.joint_model.inference(
                    [unit["text"] for unit in units],
                    labels=list(ENTITY_LABELS),
                    relations=list(self.joint_run.relation_labels),
                    threshold=self.joint_run.entity_threshold,
                    relation_threshold=self.joint_run.relation_threshold,
                    flat_ner=True,
                    batch_size=self.joint_batch_size,
                )
        else:
            entity_batches, relation_batches = [], []

        grouped_units: list[list[tuple[dict, list[dict], list[dict]]]] = [
            [] for _ in segments
        ]
        for unit, entities, relations in zip(units, entity_batches, relation_batches):
            grouped_units[unit["segment_index"]].append((unit, entities, relations))

        return [
            self._assemble_segment(segment, generated, predicted_units)
            for segment, generated, predicted_units in zip(
                segments, simplified, grouped_units
            )
        ]

    def _assemble_segment(
        self,
        segment: dict,
        generated: dict,
        predicted_units: list[tuple[dict, list[dict], list[dict]]],
    ) -> dict:
        entities: list[dict] = []
        learned_triples: list[dict] = []
        simple_sentences: list[dict] = []
        warnings: Counter[str] = Counter()
        if not generated["tagged_parse"]:
            warnings["untagged_or_unbalanced_simplifier_output"] += 1
        if not generated["sentences"]:
            warnings["empty_simplifier_output"] += 1
        if generated.get("relation_boundary_repairs"):
            warnings["relation_boundary_repaired"] += int(
                generated["relation_boundary_repairs"]
            )

        for unit, predicted_entities, predicted_relations in predicted_units:
            source_span = unit["source_span"]
            sentence_id = f"{segment.get('segment_id', 'SEG')}__G{unit['sentence_index']:03d}"
            simple_sentences.append(
                {
                    "id": sentence_id,
                    "text": unit["text"],
                    "source_start": source_span[0] if source_span else None,
                    "source_end": source_span[1] if source_span else None,
                }
            )
            if source_span is None:
                warnings["generated_sentence_not_exactly_projectable"] += 1

            local_entities: list[dict] = []
            for prediction in predicted_entities:
                start = int(prediction["start"])
                end = int(prediction["end"])
                label = str(prediction["label"]).upper()
                if (
                    label.casefold() not in ENTITY_LABELS
                    or not 0 <= start < end <= len(unit["text"])
                ):
                    warnings["invalid_entity_prediction"] += 1
                    local_entities.append({})
                    continue
                surface = unit["text"][start:end]
                projected: tuple[int, int] | None = None
                if source_span and end <= source_span[1] - source_span[0]:
                    candidate = (source_span[0] + start, source_span[0] + end)
                    if segment["text"][candidate[0] : candidate[1]].casefold() == surface.casefold():
                        projected = candidate
                if projected is None:
                    projected = _unique_surface_span(segment["text"], surface)
                doc_start = int(segment.get("doc_start", 0))
                entity = {
                    "id": f"E{len(entities) + 1}",
                    "text": surface,
                    "label": label,
                    "start": doc_start + projected[0] if projected else None,
                    "end": doc_start + projected[1] if projected else None,
                    "simple_start": start,
                    "simple_end": end,
                    "simple_sentence_id": sentence_id,
                    "score": round(float(prediction["score"]), 6),
                    "qualifiers": infer_qualifiers(
                        unit["text"],
                        {"text": surface, "label": label, "start": start, "end": end},
                        segment.get("section", "unknown"),
                    ),
                    "section": segment.get("section"),
                    "segment_id": segment.get("segment_id"),
                    "source": "simple_joint_model",
                    "source_projection": "exact" if projected else "unresolved",
                }
                if projected is None:
                    warnings["entity_not_projectable_to_source"] += 1
                entities.append(entity)
                local_entities.append(entity)

            for prediction in predicted_relations:
                head_index = _endpoint_index(prediction.get("head", {}), predicted_entities)
                tail_index = _endpoint_index(prediction.get("tail", {}), predicted_entities)
                if head_index is None or tail_index is None:
                    warnings["unresolved_relation_endpoint"] += 1
                    continue
                subject = local_entities[head_index]
                obj = local_entities[tail_index]
                if not subject or not obj:
                    warnings["relation_to_invalid_entity"] += 1
                    continue
                predicate = str(prediction.get("relation", "")).upper()
                if predicate.casefold() not in self.joint_run.relation_labels:
                    warnings["unknown_relation_label"] += 1
                    continue
                if not _valid_relation(predicate, subject, obj):
                    warnings["schema_invalid_relation"] += 1
                    continue
                if (
                    set(self.joint_run.relation_labels) != set(LEGACY_LEARNED_RELATIONS)
                    and not relation_is_compatible(predicate, subject, obj)
                ):
                    warnings["time_semantic_conflict"] += 1
                    continue
                learned_triples.append(
                    {
                        "subject_id": subject["id"],
                        "subject_text": subject["text"],
                        "subject_label": subject["label"],
                        "predicate": predicate,
                        "object_id": obj["id"],
                        "object_text": obj["text"],
                        "object_label": obj["label"],
                        "confidence": round(float(prediction["score"]), 6),
                        "source": "simple_joint_relex_model",
                        "section": segment.get("section"),
                        "segment_id": segment.get("segment_id"),
                        "simple_sentence_id": sentence_id,
                    }
                )

        case_triples: list[dict] = []
        case_id = str(segment.get("doc_id", segment.get("segment_id", "CASE")))
        for entity in entities:
            predicate = CASE_RELATIONS.get(entity["label"])
            if entity["label"] == "CONDITION" and entity["qualifiers"].get(
                "temporality"
            ) == "HISTORY":
                predicate = "HAS_HISTORY"
            if predicate:
                case_triples.append(
                    {
                        "subject_id": case_id,
                        "subject_text": "CASE",
                        "subject_label": "CASE",
                        "predicate": predicate,
                        "object_id": entity["id"],
                        "object_text": entity["text"],
                        "object_label": entity["label"],
                        "confidence": 1.0,
                        "source": "derived_from_entity_type",
                        "section": segment.get("section"),
                        "segment_id": segment.get("segment_id"),
                    }
                )

        triples = learned_triples + case_triples
        for index, triple in enumerate(triples, start=1):
            triple["id"] = f"R{index}"
        return {
            "segment_id": segment.get("segment_id"),
            "doc_id": segment.get("doc_id"),
            "section": segment.get("section"),
            "source_text": segment["text"],
            "simplifier_output": generated["raw_output"],
            "simple_sentences": simple_sentences,
            "entities": entities,
            "triples": triples,
            "statistics": {
                "simple_sentences": len(simple_sentences),
                "entities": len(entities),
                "learned_triples": len(learned_triples),
                "derived_case_triples": len(case_triples),
                "projected_entities": sum(
                    entity["source_projection"] == "exact" for entity in entities
                ),
            },
            "warnings": dict(warnings),
            "model": {
                "pipeline": "complex_to_simple_to_joint",
                "entity_threshold": self.joint_run.entity_threshold,
                "relation_threshold": self.joint_run.relation_threshold,
            },
        }


def _normalized(text: object) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().casefold()


def _score_sets(gold_sets: list[set[tuple]], pred_sets: list[set[tuple]]) -> dict:
    true_positive = sum(len(gold & pred) for gold, pred in zip(gold_sets, pred_sets))
    false_positive = sum(len(pred - gold) for gold, pred in zip(gold_sets, pred_sets))
    false_negative = sum(len(gold - pred) for gold, pred in zip(gold_sets, pred_sets))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _per_label_scores(
    gold_sets: list[set[tuple]],
    pred_sets: list[set[tuple]],
    *,
    label_position: int,
) -> dict[str, dict]:
    labels = sorted(
        {
            item[label_position]
            for items in gold_sets + pred_sets
            for item in items
        }
    )
    return {
        label: _score_sets(
            [
                {item for item in items if item[label_position] == label}
                for items in gold_sets
            ],
            [
                {item for item in items if item[label_position] == label}
                for items in pred_sets
            ],
        )
        for label in labels
    }


def evaluate_end_to_end(
    gold_records: Iterable[dict],
    predictions: Iterable[dict],
) -> dict:
    gold_records = list(gold_records)
    predictions = list(predictions)
    if len(gold_records) != len(predictions):
        raise ValueError("Số gold records và predictions không khớp")

    gold_entity_sets: list[set[tuple]] = []
    pred_entity_sets: list[set[tuple]] = []
    gold_relation_sets: list[set[tuple]] = []
    pred_relation_sets: list[set[tuple]] = []
    for gold, predicted in zip(gold_records, predictions):
        gold_entities = {
            str(entity["id"]): entity for entity in gold.get("entities", [])
        }
        gold_entity_sets.append(
            {
                (str(entity["label"]).upper(), _normalized(entity["text"]))
                for entity in gold_entities.values()
            }
        )
        pred_entity_sets.append(
            {
                (str(entity["label"]).upper(), _normalized(entity["text"]))
                for entity in predicted.get("entities", [])
            }
        )
        gold_relations: set[tuple] = set()
        for relation in gold.get("relations", []):
            predicate = str(relation.get("predicate", "")).upper()
            if predicate.casefold() not in LEARNED_RELATIONS:
                continue
            head = gold_entities.get(str(relation.get("subject")))
            tail = gold_entities.get(str(relation.get("object")))
            if head and tail:
                gold_relations.add(
                    (
                        str(head["label"]).upper(),
                        _normalized(head["text"]),
                        predicate,
                        str(tail["label"]).upper(),
                        _normalized(tail["text"]),
                    )
                )
        gold_relation_sets.append(gold_relations)
        pred_relation_sets.append(
            {
                (
                    str(triple["subject_label"]).upper(),
                    _normalized(triple["subject_text"]),
                    str(triple["predicate"]).upper(),
                    str(triple["object_label"]).upper(),
                    _normalized(triple["object_text"]),
                )
                for triple in predicted.get("triples", [])
                if triple.get("source") == "simple_joint_relex_model"
            }
        )

    warnings: Counter[str] = Counter()
    for predicted in predictions:
        warnings.update(predicted.get("warnings", {}))
    return {
        "evaluation_scope": "end_to_end_generated_simple_sentences",
        "match_definition": (
            "unique normalized surface+label within each source segment; relation also "
            "requires normalized head/predicate/tail"
        ),
        "records": len(gold_records),
        "entity_micro": _score_sets(gold_entity_sets, pred_entity_sets),
        "entity_per_label": _per_label_scores(
            gold_entity_sets, pred_entity_sets, label_position=0
        ),
        "relation_micro": _score_sets(gold_relation_sets, pred_relation_sets),
        "relation_per_label": _per_label_scores(
            gold_relation_sets, pred_relation_sets, label_position=2
        ),
        "simplifier_parse_success": (
            sum(not item.get("warnings", {}).get("untagged_or_unbalanced_simplifier_output") for item in predictions)
            / len(predictions)
            if predictions
            else 0.0
        ),
        "source_projection": {
            "entities": sum(len(item.get("entities", [])) for item in predictions),
            "exact": sum(
                entity.get("source_projection") == "exact"
                for item in predictions
                for entity in item.get("entities", [])
            ),
        },
        "warnings": dict(warnings),
    }


def format_simple_demo(result: dict) -> str:
    lines = [
        "PIPELINE: complex → simple → joint NER/RelEx",
        "",
        "CÂU ĐƠN SINH RA",
    ]
    if not result.get("simple_sentences"):
        lines.append("(không sinh được câu đơn)")
    for index, sentence in enumerate(result.get("simple_sentences", []), start=1):
        lines.append(f"{index}. {sentence['text']}")
    lines.extend(["", "THỰC THỂ"])
    if not result.get("entities"):
        lines.append("(không có)")
    for entity in result.get("entities", []):
        projection = (
            f"source[{entity['start']}:{entity['end']}]"
            if entity.get("start") is not None
            else "không chiếu được về nguồn"
        )
        lines.append(
            f"{entity['id']} | {entity['label']} | {entity['score']:.3f} | "
            f"{entity['text']} | {projection}"
        )
    lines.extend(["", "S-P-O DO JOINT MODEL"])
    learned = [
        triple
        for triple in result.get("triples", [])
        if triple.get("source") == "simple_joint_relex_model"
    ]
    if not learned:
        lines.append("(không có quan hệ vượt threshold)")
    for triple in learned:
        lines.append(
            f"{triple['subject_text']} [{triple['subject_label']}] "
            f"--{triple['predicate']} ({triple['confidence']:.3f})--> "
            f"{triple['object_text']} [{triple['object_label']}]"
        )
    if result.get("warnings"):
        lines.extend(["", f"CẢNH BÁO: {result['warnings']}"])
    return "\n".join(lines)
