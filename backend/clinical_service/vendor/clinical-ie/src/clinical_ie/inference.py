from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .preprocess import (
    anonymize_text,
    canonical_content,
    iter_segments,
    normalize_text,
    parse_sections,
    stable_id,
)
from .rules import CASE_RELATIONS, infer_qualifiers
from .training import (
    ENTITY_LABELS,
    LEGACY_LEARNED_RELATIONS,
    LEARNED_RELATIONS,
    relation_labels_from_metrics,
    sha256_file,
)


RELATION_SIGNATURES = {
    "HAS_RESULT": ({"TEST"}, {"RESULT"}),
    "REVEALS": ({"TEST"}, {"SIGN", "CONDITION", "RESULT"}),
    "LOCATED_AT": (
        {"SYMPTOM", "SIGN", "CONDITION", "TEST", "TREATMENT"},
        {"ANATOMY"},
    ),
    "OCCURS_AT": (
        {"SYMPTOM", "SIGN", "CONDITION", "TEST", "RESULT", "TREATMENT"},
        {"TIME"},
    ),
    "HAS_DURATION": (
        {"SYMPTOM", "SIGN", "CONDITION", "TEST", "RESULT", "TREATMENT"},
        {"TIME"},
    ),
    "ONSET_AT": (
        {"SYMPTOM", "SIGN", "CONDITION", "TEST", "RESULT", "TREATMENT"},
        {"TIME"},
    ),
    "HAS_FREQUENCY": (
        {"SYMPTOM", "SIGN", "CONDITION", "TEST", "RESULT", "TREATMENT"},
        {"TIME"},
    ),
    "TREATED_WITH": ({"SYMPTOM", "CONDITION"}, {"TREATMENT"}),
    "IMPROVED_BY": ({"SYMPTOM", "CONDITION"}, {"TREATMENT"}),
    "NOT_IMPROVED_BY": ({"SYMPTOM", "CONDITION"}, {"TREATMENT"}),
}

DEFAULT_DEMO_TEXT = (
    "Bệnh nhân khó thở 3 ngày, SpO2 85%, phổi trái có ran ẩm "
    "và điều trị Ceftriaxone."
)


@dataclass(frozen=True)
class ModelRun:
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
        return json.load(handle)


def read_jsonl(path: str | Path) -> Iterator[dict]:
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def build_demo_document(raw_text: str, *, section: str = "auto") -> dict:
    """Build a de-identified in-memory document for the interactive CLI demo."""
    normalized = normalize_text(raw_text)
    if not normalized:
        raise ValueError("Văn bản demo đang rỗng")
    anonymized, pii_counts = anonymize_text(normalized)
    parsed_sections = (
        parse_sections(anonymized)
        if section == "auto"
        else [{"name": section, "text": anonymized}]
    )

    cursor = 0
    parts: list[str] = []
    sections: list[dict] = []
    for parsed in parsed_sections:
        if parts:
            parts.append("\n")
            cursor += 1
        start = cursor
        parts.append(parsed["text"])
        cursor += len(parsed["text"])
        sections.append({
            "name": parsed["name"],
            "text": parsed["text"],
            "doc_start": start,
            "doc_end": cursor,
        })
    text = "".join(parts)
    canonical = canonical_content(text)
    return {
        "doc_id": stable_id(canonical, prefix="DEMO"),
        "content_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "disease_labels": [],
        "text": text,
        "sections": sections,
        "pii_counts": pii_counts,
    }


def format_demo_output(record: dict) -> str:
    """Render a compact Vietnamese explanation for a live terminal demo."""
    lines = [
        f"BỆNH ÁN DEMO: {record['doc_id']}",
        f"Số thực thể: {len(record.get('entities', []))}",
        f"Số S-P-O: {len(record.get('triples', []))}",
        "",
        "THỰC THỂ",
        "ID | NHÃN | SCORE | VĂN BẢN | QUALIFIER",
    ]
    for entity in record.get("entities", []):
        qualifiers = ", ".join(
            f"{key}={value}" for key, value in entity.get("qualifiers", {}).items()
        )
        lines.append(
            f"{entity['id']} | {entity['label']} | {entity['score']:.3f} | "
            f"{entity['text']} | {qualifiers or '-'}"
        )

    learned = [
        triple
        for triple in record.get("triples", [])
        if triple.get("source") == "joint_relex_model"
    ]
    derived = [
        triple
        for triple in record.get("triples", [])
        if triple.get("source") == "derived_from_entity_type"
    ]
    lines.extend(["", "S-P-O DO MODEL DỰ ĐOÁN"])
    if not learned:
        lines.append("(không có quan hệ vượt threshold)")
    for triple in learned:
        lines.append(
            f"{triple['subject_text']} [{triple['subject_label']}] "
            f"--{triple['predicate']} ({triple['confidence']:.3f})--> "
            f"{triple['object_text']} [{triple['object_label']}]"
        )

    lines.extend(["", "S-P-O SUY RA TỪ LOẠI THỰC THỂ"])
    if not derived:
        lines.append("(không có)")
    for triple in derived:
        lines.append(
            f"CASE --{triple['predicate']}--> "
            f"{triple['object_text']} [{triple['object_label']}]"
        )
    if record.get("warnings"):
        lines.extend(["", f"CẢNH BÁO: {record['warnings']}"])
    return "\n".join(lines)


def iter_document_shard(
    documents: Iterable[dict],
    *,
    shard_count: int,
    shard_index: int,
) -> Iterator[dict]:
    if shard_count < 1:
        raise ValueError("shard_count phải lớn hơn 0")
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index phải nằm trong [0, shard_count)")
    for index, document in enumerate(documents):
        if index % shard_count == shard_index:
            yield document


def merge_inference_outputs(
    input_paths: Iterable[str | Path],
    output_path: str | Path,
) -> dict:
    """Merge independent shard JSONL files without loading predictions into RAM."""
    paths = [Path(path).resolve() for path in input_paths]
    if not paths:
        raise ValueError("Cần ít nhất một shard để merge")
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Không thấy shard: {path}")
    output_path = Path(output_path).resolve()
    if output_path in paths:
        raise ValueError("Output merge không được trùng với input shard")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    records = 0
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=output_path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        try:
            for path in paths:
                with path.open(encoding="utf-8") as source:
                    for line_number, line in enumerate(source, start=1):
                        if not line.strip():
                            continue
                        record = json.loads(line)
                        doc_id = record.get("doc_id")
                        if not isinstance(doc_id, str):
                            raise ValueError(f"Thiếu doc_id: {path}:{line_number}")
                        if doc_id in seen:
                            raise ValueError(f"Trùng doc_id khi merge: {doc_id}")
                        seen.add(doc_id)
                        handle.write(line.rstrip("\n"))
                        handle.write("\n")
                        records += 1
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(temporary, output_path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    return {
        "status": "PASS",
        "inputs": [str(path) for path in paths],
        "output": str(output_path),
        "records": records,
        "unique_doc_ids": len(seen),
        "output_sha256": sha256_file(output_path),
    }


def resolve_joint_model_run(
    models_root: str | Path,
    model_run: str | Path | None = None,
) -> ModelRun:
    """Find and validate the locally downloaded joint NER/RelEx run."""
    if model_run is not None:
        requested = Path(model_run).expanduser().resolve()
        run_dir = requested.parent if requested.name == "final_model" else requested
        candidates = [run_dir]
    else:
        root = Path(models_root).expanduser().resolve()
        candidates = []
        if root.is_dir():
            for metrics_path in sorted(root.glob("*/metrics.json")):
                try:
                    metrics = _load_json(metrics_path)
                except (OSError, json.JSONDecodeError):
                    continue
                if metrics.get("task") == "joint_ner_relex":
                    candidates.append(metrics_path.parent)

    if not candidates:
        raise FileNotFoundError(
            "Không tìm thấy model joint NER/RelEx local. Dùng --model-run để chỉ "
            "đến thư mục chứa final_model/ và metrics.json."
        )
    if len(candidates) > 1:
        raise ValueError(
            "Có nhiều model joint NER/RelEx; hãy chọn một bằng --model-run: "
            + ", ".join(str(path) for path in candidates)
        )

    run_dir = candidates[0]
    metrics_path = run_dir / "metrics.json"
    final_model_dir = run_dir / "final_model"
    config_path = final_model_dir / "gliner_config.json"
    weight_paths = [
        path
        for path in (
            final_model_dir / "model.safetensors",
            final_model_dir / "pytorch_model.bin",
        )
        if path.exists()
    ]
    missing = [
        path
        for path in (metrics_path, config_path)
        if not path.is_file()
    ]
    if missing or not weight_paths:
        details = [str(path) for path in missing]
        if not weight_paths:
            details.append("model.safetensors|pytorch_model.bin")
        raise FileNotFoundError("Model run chưa đầy đủ: " + ", ".join(details))

    metrics = _load_json(metrics_path)
    if metrics.get("task") != "joint_ner_relex":
        raise ValueError(f"Metrics không phải joint NER/RelEx: {metrics_path}")
    entity_threshold = float(metrics["entity_threshold"])
    relation_threshold = float(metrics["best_dev_relation_threshold"])
    if not (0.0 <= entity_threshold <= 1.0 and 0.0 <= relation_threshold <= 1.0):
        raise ValueError("Threshold trong metrics.json nằm ngoài [0, 1]")

    return ModelRun(
        run_dir=run_dir,
        final_model_dir=final_model_dir,
        metrics_path=metrics_path,
        metrics=metrics,
        entity_threshold=entity_threshold,
        relation_threshold=relation_threshold,
        weight_path=weight_paths[0],
        relation_labels=relation_labels_from_metrics(metrics),
    )


def resolve_device(requested: str, torch_module) -> str:
    requested = requested.casefold()
    if requested == "auto":
        if torch_module.cuda.is_available():
            return "cuda"
        if torch_module.backends.mps.is_available():
            return "mps"
        return "cpu"
    if requested == "cuda" and not torch_module.cuda.is_available():
        raise RuntimeError("CUDA được yêu cầu nhưng torch.cuda.is_available() là False")
    if requested == "mps" and not torch_module.backends.mps.is_available():
        raise RuntimeError("MPS được yêu cầu nhưng torch.backends.mps.is_available() là False")
    if requested not in {"cpu", "cuda", "mps"}:
        raise ValueError(f"Thiết bị không hợp lệ: {requested}")
    return requested


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


def relation_is_compatible(predicate: str, subject: dict, obj: dict) -> bool:
    """Validate both endpoint types and unambiguous TIME surface semantics."""
    signature = RELATION_SIGNATURES.get(predicate)
    if signature is None:
        return False
    allowed_subjects, allowed_objects = signature
    if subject["label"] not in allowed_subjects or obj["label"] not in allowed_objects:
        return False
    if obj["label"] != "TIME":
        return True

    surface = str(obj.get("text", ""))
    duration = bool(re.search(
        r"\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?\s*(?:giờ|h|ngày|tuần|tháng|năm)\b",
        surface,
        re.IGNORECASE,
    ))
    frequency = bool(re.search(
        r"lần\s*/|từng\s+cơn|liên\s+tục|thường\s+xuyên",
        surface,
        re.IGNORECASE,
    ))
    onset = bool(re.search(
        r"cách\s+(?:ngày\s+)?nhập\s+viện|cùng\s+ngày|sáng\s+nay|chiều\s+nay|hôm\s+nay",
        surface,
        re.IGNORECASE,
    ))
    if predicate == "HAS_DURATION":
        return duration and not frequency
    if predicate == "HAS_FREQUENCY":
        return frequency
    if predicate == "ONSET_AT":
        return not frequency
    if predicate == "OCCURS_AT":
        return not duration and not frequency and not onset
    return True


def _valid_relation(predicate: str, subject: dict, obj: dict) -> bool:
    signature = RELATION_SIGNATURES.get(predicate)
    if signature is None:
        return False
    allowed_subjects, allowed_objects = signature
    return subject["label"] in allowed_subjects and obj["label"] in allowed_objects


def assemble_document_output(
    document: dict,
    segments: list[dict],
    entity_batches: list[list[dict]],
    relation_batches: list[list[dict]],
    *,
    model_run: ModelRun,
    include_text: bool = False,
) -> dict:
    """Convert segment predictions to document offsets and explicit S-P-O triples."""
    if not (len(segments) == len(entity_batches) == len(relation_batches)):
        raise ValueError("Số segment và batch dự đoán không khớp")

    entities: list[dict] = []
    learned_triples: list[dict] = []
    warnings: Counter[str] = Counter()

    for segment, predicted_entities, predicted_relations in zip(
        segments, entity_batches, relation_batches
    ):
        local_entities: list[dict] = []
        for prediction in predicted_entities:
            start = int(prediction["start"])
            end = int(prediction["end"])
            label = str(prediction["label"]).upper()
            if (
                label.casefold() not in ENTITY_LABELS
                or not (0 <= start < end <= len(segment["text"]))
            ):
                warnings["invalid_entity_prediction"] += 1
                local_entities.append({})
                continue
            entity = {
                "id": f"E{len(entities) + 1}",
                "text": segment["text"][start:end],
                "label": label,
                "start": segment["doc_start"] + start,
                "end": segment["doc_start"] + end,
                "score": round(float(prediction["score"]), 6),
                "qualifiers": infer_qualifiers(
                    segment["text"],
                    {
                        "text": segment["text"][start:end],
                        "label": label,
                        "start": start,
                        "end": end,
                    },
                    segment["section"],
                ),
                "section": segment["section"],
                "segment_id": segment["segment_id"],
                "source": "joint_relex_model",
            }
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
            if predicate.casefold() not in model_run.relation_labels:
                warnings["unknown_relation_label"] += 1
                continue
            if not _valid_relation(predicate, subject, obj):
                warnings["schema_invalid_relation"] += 1
                continue
            if (
                set(model_run.relation_labels) != set(LEGACY_LEARNED_RELATIONS)
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
                    "source": "joint_relex_model",
                    "section": segment["section"],
                    "segment_id": segment["segment_id"],
                }
            )

    by_id = {entity["id"]: entity for entity in entities}
    for triple in learned_triples:
        if triple["predicate"] != "LOCATED_AT":
            continue
        subject = by_id[triple["subject_id"]]
        anatomy = by_id[triple["object_id"]]
        laterality = anatomy["qualifiers"].get("laterality")
        if laterality and "laterality" not in subject["qualifiers"]:
            subject["qualifiers"]["laterality"] = laterality

    case_triples: list[dict] = []
    for entity in entities:
        predicate = CASE_RELATIONS.get(entity["label"])
        if (
            entity["label"] == "CONDITION"
            and entity["qualifiers"].get("temporality") == "HISTORY"
        ):
            predicate = "HAS_HISTORY"
        if predicate is None:
            continue
        case_triples.append(
            {
                "subject_id": document["doc_id"],
                "subject_text": "CASE",
                "subject_label": "CASE",
                "predicate": predicate,
                "object_id": entity["id"],
                "object_text": entity["text"],
                "object_label": entity["label"],
                "confidence": 1.0,
                "source": "derived_from_entity_type",
                "section": entity["section"],
                "segment_id": entity["segment_id"],
            }
        )

    unique: dict[tuple[str, str, str], dict] = {}
    for triple in learned_triples + case_triples:
        key = (triple["subject_id"], triple["predicate"], triple["object_id"])
        if key not in unique or triple["confidence"] > unique[key]["confidence"]:
            unique[key] = triple
    triples = list(unique.values())
    for index, triple in enumerate(triples, start=1):
        triple["id"] = f"R{index}"
    learned_count = sum(
        triple["source"] == "joint_relex_model" for triple in triples
    )
    derived_count = len(triples) - learned_count

    output = {
        "doc_id": document["doc_id"],
        "content_hash": document.get("content_hash"),
        "disease_labels": list(document.get("disease_labels", [])),
        "disease_labels_usage": "classification_target_only_not_model_input",
        "entities": entities,
        "triples": triples,
        "statistics": {
            "segments": len(segments),
            "entities": len(entities),
            "learned_triples": learned_count,
            "derived_case_triples": derived_count,
        },
        "warnings": dict(warnings),
        "model": {
            "task": "joint_ner_relex",
            "entity_threshold": model_run.entity_threshold,
            "relation_threshold": model_run.relation_threshold,
            "relation_labels": list(model_run.relation_labels),
        },
    }
    if include_text:
        output["text"] = document.get("text", "")
    return output


class ClinicalIEExtractor:
    def __init__(
        self,
        model_run: ModelRun,
        *,
        device: str = "auto",
        batch_size: int = 4,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size phải lớn hơn 0")
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        try:
            import torch
            from gliner.model import UniEncoderTokenRelexGLiNER
        except ImportError as error:
            raise RuntimeError(
                "Thiếu dependency inference. Cài bằng: pip install -e '.[inference]'"
            ) from error

        self.torch = torch
        self.model_run = model_run
        self.device = resolve_device(device, torch)
        self.batch_size = batch_size
        self.model = UniEncoderTokenRelexGLiNER.from_pretrained(
            str(model_run.final_model_dir),
            local_files_only=True,
            map_location="cpu",
        )
        if self.model.config.model_type != "gliner_uni_encoder_token_relex":
            raise RuntimeError(
                f"Sai kiến trúc model: {self.model.config.model_type}"
            )
        self.model.to(self.device)
        self.model.eval()

    def extract_document(self, document: dict, *, include_text: bool = False) -> dict:
        return self.extract_documents([document], include_text=include_text)[0]

    def extract_documents(
        self,
        documents: list[dict],
        *,
        include_text: bool = False,
    ) -> list[dict]:
        """Infer several documents in one DataLoader while preserving boundaries."""
        segments_by_document = [list(iter_segments(document)) for document in documents]
        flat_segments = [
            segment
            for document_segments in segments_by_document
            for segment in document_segments
        ]
        if flat_segments:
            with self.torch.inference_mode():
                flat_entities, flat_relations = self.model.inference(
                    [segment["text"] for segment in flat_segments],
                    labels=list(ENTITY_LABELS),
                    relations=list(self.model_run.relation_labels),
                    threshold=self.model_run.entity_threshold,
                    relation_threshold=self.model_run.relation_threshold,
                    flat_ner=True,
                    batch_size=self.batch_size,
                )
        else:
            flat_entities, flat_relations = [], []

        outputs: list[dict] = []
        cursor = 0
        for document, document_segments in zip(documents, segments_by_document):
            end = cursor + len(document_segments)
            outputs.append(
                assemble_document_output(
                    document,
                    document_segments,
                    flat_entities[cursor:end],
                    flat_relations[cursor:end],
                    model_run=self.model_run,
                    include_text=include_text,
                )
            )
            cursor = end
        return outputs


def summarize_output(path: str | Path) -> dict:
    documents = segments = entities = learned = derived = 0
    entity_labels: Counter[str] = Counter()
    predicates: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    for record in read_jsonl(path):
        documents += 1
        segments += int(record.get("statistics", {}).get("segments", 0))
        entities += len(record.get("entities", []))
        entity_labels.update(entity["label"] for entity in record.get("entities", []))
        for triple in record.get("triples", []):
            predicates[triple["predicate"]] += 1
            if triple["source"] == "joint_relex_model":
                learned += 1
            else:
                derived += 1
        warnings.update(record.get("warnings", {}))
    return {
        "documents": documents,
        "segments": segments,
        "entities": entities,
        "learned_triples": learned,
        "derived_case_triples": derived,
        "entity_labels": dict(entity_labels.most_common()),
        "predicates": dict(predicates.most_common()),
        "warnings": dict(warnings),
    }


def audit_inference_output(
    output_path: str | Path,
    documents_path: str | Path,
    *,
    allow_partial: bool = False,
) -> dict:
    """Validate offsets, entity references, relation signatures and coverage."""
    documents = {
        document["doc_id"]: document
        for document in read_jsonl(documents_path)
    }
    seen_documents: set[str] = set()
    errors: list[dict] = []
    entity_counts: Counter[str] = Counter()
    predicate_counts: Counter[str] = Counter()
    record_count = 0

    def add_error(doc_id: str, code: str, detail: object) -> None:
        if len(errors) < 100:
            errors.append({"doc_id": doc_id, "code": code, "detail": detail})

    for record in read_jsonl(output_path):
        record_count += 1
        doc_id = record.get("doc_id")
        if not isinstance(doc_id, str):
            add_error("UNKNOWN", "missing_doc_id", None)
            continue
        if doc_id in seen_documents:
            add_error(doc_id, "duplicate_doc_id", None)
            continue
        seen_documents.add(doc_id)
        document = documents.get(doc_id)
        if document is None:
            add_error(doc_id, "unknown_doc_id", None)
            continue
        if record.get("disease_labels") != document.get("disease_labels", []):
            add_error(doc_id, "disease_labels_mismatch", record.get("disease_labels"))

        entities_by_id: dict[str, dict] = {}
        for entity in record.get("entities", []):
            entity_id = entity.get("id")
            if not isinstance(entity_id, str) or entity_id in entities_by_id:
                add_error(doc_id, "invalid_or_duplicate_entity_id", entity_id)
                continue
            entities_by_id[entity_id] = entity
            label = entity.get("label")
            if not isinstance(label, str) or label.casefold() not in ENTITY_LABELS:
                add_error(doc_id, "invalid_entity_label", label)
                continue
            entity_counts[label] += 1
            start, end = entity.get("start"), entity.get("end")
            if not (
                isinstance(start, int)
                and isinstance(end, int)
                and 0 <= start < end <= len(document["text"])
            ):
                add_error(doc_id, "invalid_entity_offset", [start, end])
                continue
            if document["text"][start:end] != entity.get("text"):
                add_error(doc_id, "entity_text_offset_mismatch", entity_id)

        triple_ids: set[str] = set()
        for triple in record.get("triples", []):
            triple_id = triple.get("id")
            if not isinstance(triple_id, str) or triple_id in triple_ids:
                add_error(doc_id, "invalid_or_duplicate_triple_id", triple_id)
                continue
            triple_ids.add(triple_id)
            predicate = triple.get("predicate")
            if isinstance(predicate, str):
                predicate_counts[predicate] += 1
            subject_id = triple.get("subject_id")
            object_id = triple.get("object_id")
            obj = entities_by_id.get(object_id)
            if obj is None:
                add_error(doc_id, "unknown_triple_object", object_id)
                continue
            if subject_id == doc_id:
                if triple.get("source") != "derived_from_entity_type":
                    add_error(doc_id, "invalid_case_triple_source", triple_id)
                continue
            subject = entities_by_id.get(subject_id)
            if subject is None:
                add_error(doc_id, "unknown_triple_subject", subject_id)
                continue
            if triple.get("source") == "joint_relex_model" and not _valid_relation(
                str(predicate), subject, obj
            ):
                add_error(doc_id, "schema_invalid_learned_triple", triple_id)

    missing_documents = sorted(set(documents) - seen_documents)
    if missing_documents and not allow_partial:
        add_error(
            "GLOBAL",
            "missing_documents",
            {"count": len(missing_documents), "examples": missing_documents[:10]},
        )
    return {
        "status": "PASS" if not errors else "FAIL",
        "allow_partial": allow_partial,
        "expected_documents": len(documents),
        "observed_documents": record_count,
        "unique_observed_documents": len(seen_documents),
        "missing_documents": len(missing_documents),
        "errors": errors,
        "entity_labels": dict(entity_counts.most_common()),
        "predicates": dict(predicate_counts.most_common()),
        "output_sha256": sha256_file(output_path),
    }


def run_inference(
    extractor: ClinicalIEExtractor,
    documents: Iterable[dict],
    output_path: str | Path,
    *,
    input_path: str | Path,
    include_text: bool = False,
    resume: bool = False,
    limit: int | None = None,
    progress_every: int = 25,
    document_batch_size: int = 16,
) -> dict:
    if limit is not None and limit < 1:
        raise ValueError("limit phải lớn hơn 0")
    if document_batch_size < 1:
        raise ValueError("document_batch_size phải lớn hơn 0")
    output_path = Path(output_path).resolve()
    if output_path == Path(input_path).resolve():
        raise ValueError("Input và output inference không được trùng nhau")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids: set[str] = set()
    if resume and output_path.exists():
        existing_ids = {record["doc_id"] for record in read_jsonl(output_path)}

    started = time.monotonic()
    processed = 0
    skipped = 0
    next_progress = progress_every if progress_every > 0 else None
    mode = "a" if resume else "w"

    def write_batch(handle, document_batch: list[dict]) -> int:
        if not document_batch:
            return 0
        results = extractor.extract_documents(
            document_batch,
            include_text=include_text,
        )
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        handle.flush()
        return len(results)

    with output_path.open(mode, encoding="utf-8") as handle:
        pending: list[dict] = []
        for document in documents:
            if document["doc_id"] in existing_ids:
                skipped += 1
                continue
            if limit is not None and processed + len(pending) >= limit:
                break
            pending.append(document)
            if len(pending) >= document_batch_size:
                processed += write_batch(handle, pending)
                pending = []
                if next_progress is not None and processed >= next_progress:
                    print(f"Đã xử lý {processed} bệnh án mới")
                    while next_progress <= processed:
                        next_progress += progress_every
        if pending:
            processed += write_batch(handle, pending)
            if next_progress is not None and processed >= next_progress:
                print(f"Đã xử lý {processed} bệnh án mới")

    elapsed = time.monotonic() - started
    summary = summarize_output(output_path)
    return {
        "status": "PASS",
        "input": str(Path(input_path).resolve()),
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
        "model_run": str(extractor.model_run.run_dir),
        "weight_file": extractor.model_run.weight_path.name,
        "weight_bytes": extractor.model_run.weight_path.stat().st_size,
        "device": extractor.device,
        "batch_size": extractor.batch_size,
        "document_batch_size": document_batch_size,
        "entity_threshold": extractor.model_run.entity_threshold,
        "relation_threshold": extractor.model_run.relation_threshold,
        "disease_labels_used_as_model_input": False,
        "resumed": resume,
        "skipped_existing_documents": skipped,
        "new_documents": processed,
        "elapsed_seconds": round(elapsed, 3),
        "documents_per_second": round(processed / elapsed, 4) if elapsed else None,
        "summary": summary,
        "reference_test_metrics": {
            "entity_micro": extractor.model_run.metrics.get("test_entity_micro"),
            "relation_micro": extractor.model_run.metrics.get("test_relation_micro"),
            "relation_per_label": extractor.model_run.metrics.get("test_relation_per_label"),
        },
    }
