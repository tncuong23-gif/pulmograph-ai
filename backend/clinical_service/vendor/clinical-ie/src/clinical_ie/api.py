"""Public high-level API and ResearchAssistant facade for gliner-clinical-ie.

Contracts:
- Unified user inputs:
  1. Single-turn Vietnamese symptom description question (ask_symptoms)
  2. Clinical medical record TXT file (analyze_file)
  3. Raw medical-record text (analyze_text)
  4. Independent entity strings (analyze_entities), no invented inter-item SPO
- Both return Top 5 in 12 classes via the configured classifier bundle, missing information flags,
  and up to 3 de-identified reference cases.
- Classifier determines disease ranking; reference cases are strictly reference context
  and do not alter scores.
- Decision scores are NOT clinical diagnostic probabilities.
- Air-gapped offline execution: no network calls, explicit paths.
"""
from __future__ import annotations

import json
import math
import os
import platform
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from .classification import LABELS
from .classification.hybrid import HybridClassifier, HybridPrediction, TopClass
from .classification.late_fusion import LateFusionClassifier
from .graph import (
    build_case_graph,
    deduplicate_case_graph,
    export_graph_jsonl,
    export_neo4j_cypher,
    validate_case_graph,
)
from .models import BundleInfo, resolve_device, verify_bundle
from .retrieval.reference_index import ReferenceIndex, SimilarCaseSummary
from .retrieval.clinical_context import OBSERVED, contains_phrase, extract_retrieval_vitals, normalize

RESEARCH_DISCLAIMER = (
    "Sản phẩm nghiên cứu/học tập; không phải thiết bị y tế hay công cụ chẩn đoán lâm sàng "
    "dùng cho bệnh nhân thực tế. Điểm phân lớp là điểm quyết định mô hình (decision scores) "
    "phục vụ xếp hạng, không phải xác suất chẩn đoán."
)

CLINICAL_QUESTIONS_BANK = [
    "Bạn có bị sốt không? Nhiệt độ đo được là bao nhiêu độ C?",
    "Triệu chứng xuất hiện bao lâu rồi (dưới 7 ngày hay kéo dài nhiều tuần)?",
    "Có kèm theo khó thở, thở rít, đau tức ngực hay ho khạc đờm không?",
    "Bạn đã đo độ bão hòa oxy máu (SpO2) chưa? Chỉ số là bao nhiêu %?",
    "Bạn có tiền sử bệnh phổi (hen suyễn, COPD, lao) hoặc hút thuốc lá không?",
]


@dataclass(frozen=True)
class ExtractionResult:
    doc_id: str
    text: str
    entities: list[dict[str, Any]]
    triples: list[dict[str, Any]]
    status: str
    engine: str = "vit5_joint_v1_3"
    provenance: dict[str, Any] = field(default_factory=dict)
    quarantined: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    statistics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "text": self.text,
            "entities": self.entities,
            "triples": self.triples,
            "status": self.status,
            "engine": self.engine,
            "provenance": self.provenance,
            "quarantined": self.quarantined,
            "warnings": self.warnings,
            "statistics": self.statistics,
        }


@dataclass(frozen=True)
class AnalysisResult:
    """Output container for medical record TXT file analysis."""

    input_type: str
    document_id: str
    status: str
    schema_version: str
    top5: list[dict[str, Any]]
    all_scores: dict[str, float]
    all_probabilities: dict[str, float]
    graph: dict[str, Any]
    extracted_facts: dict[str, Any]
    missing_information_questions: list[str]
    similar_cases: list[dict[str, Any]]
    model_versions: dict[str, str]
    engine: str = "vit5_joint_v1_3"
    filter_provenance: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_type": self.input_type,
            "document_id": self.document_id,
            "status": self.status,
            "schema_version": self.schema_version,
            "engine": self.engine,
            "top5": self.top5,
            "all_scores": self.all_scores,
            "all_probabilities": self.all_probabilities,
            "graph": self.graph,
            "extracted_facts": self.extracted_facts,
            "missing_information_questions": self.missing_information_questions,
            "similar_cases": self.similar_cases,
            "model_versions": self.model_versions,
            "filter_provenance": self.filter_provenance,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class QueryAnswer:
    """Output container for single-turn Vietnamese symptom description question."""

    input_type: str
    question: str
    status: str
    schema_version: str
    top5: list[dict[str, Any]]
    all_scores: dict[str, float]
    all_probabilities: dict[str, float]
    extracted_facts: dict[str, Any]
    missing_information_questions: list[str]
    similar_cases: list[dict[str, Any]]
    model_versions: dict[str, str]
    engine: str = "vit5_joint_v1_3"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_type": self.input_type,
            "question": self.question,
            "status": self.status,
            "schema_version": self.schema_version,
            "engine": self.engine,
            "top5": self.top5,
            "all_scores": self.all_scores,
            "all_probabilities": self.all_probabilities,
            "extracted_facts": self.extracted_facts,
            "missing_information_questions": self.missing_information_questions,
            "similar_cases": self.similar_cases,
            "model_versions": self.model_versions,
            "warnings": self.warnings,
        }


class ClinicalPipeline:
    """Information Extraction pipeline for entities, qualifiers, and S-P-O relations."""

    def __init__(
        self,
        inner_pipeline: Any = None,
        device: str = "cpu",
        engine: str = "vit5_joint_v1_3",
    ) -> None:
        self.inner = inner_pipeline
        self.device = device
        self.engine = engine if inner_pipeline is not None else "rule_fallback"

    @classmethod
    def from_bundle(
        cls,
        bundle_dir: str | Path,
        *,
        device: str = "auto",
        config: dict[str, Any] | None = None,
    ) -> ClinicalPipeline:
        """Load simplifier and joint IE models from explicit bundle directory."""
        resolved_device = resolve_device(device)
        b_path = Path(bundle_dir).resolve()
        if not b_path.is_dir():
            raise FileNotFoundError(f"IE bundle directory not found: {b_path}")

        v_info = verify_bundle(b_path, expected_kind="ie")
        if not v_info.is_valid:
            raise ValueError(f"IE bundle verification failed: {v_info.errors}")

        # Check for simplifier and joint subdirectories
        simplifier_dir = b_path / "simplifier"
        if not simplifier_dir.is_dir():
            # Check models root layout fallback
            for candidate in sorted(b_path.glob("vit5*")):
                if candidate.is_dir():
                    simplifier_dir = candidate
                    break

        joint_dir = b_path / "joint"
        if not joint_dir.is_dir():
            for candidate in sorted(b_path.glob("relex*")):
                if candidate.is_dir():
                    joint_dir = candidate
                    break

        if not simplifier_dir.is_dir() or not joint_dir.is_dir():
            raise FileNotFoundError(
                f"IE bundle at {b_path} must contain 'simplifier' and 'joint' model runs"
            )

        from .simple_pipeline import (
            SimpleJointPipeline,
            resolve_simple_joint_run,
            resolve_simplifier_run,
        )

        simplifier_run = resolve_simplifier_run(b_path, simplifier_dir)
        joint_run = resolve_simple_joint_run(b_path, joint_dir)

        inner = SimpleJointPipeline(
            simplifier_run,
            joint_run,
            device=resolved_device,
        )
        return cls(inner_pipeline=inner, device=resolved_device, engine="vit5_joint_v1_3")

    def extract_text(self, text: str, *, document_id: str | None = None) -> ExtractionResult:
        doc_id = document_id or f"doc_{int(time.time() * 1000)}"
        clean_text = (text or "").strip()
        if not clean_text:
            return ExtractionResult(
                doc_id=doc_id,
                text="",
                entities=[],
                triples=[],
                status="empty_input",
                engine=self.engine,
                warnings=["Văn bản đầu vào rỗng."],
            )

        if self.inner is None:
            # Fallback rule-based extractor when deep IE model not loaded
            from .rules import preannotate_segment
            dummy_seg = {"doc_id": doc_id, "segment_id": "seg_01", "text": clean_text, "section": "symptoms"}
            annotated = preannotate_segment(dummy_seg)
            entities = annotated.get("entities", [])
            raw_relations = annotated.get("relations", [])
            triples = []
            for r in raw_relations:
                triples.append({
                    "id": r.get("id"),
                    "subject_id": r.get("subject_id") or r.get("subject"),
                    "object_id": r.get("object_id") or r.get("object"),
                    "predicate": r.get("predicate"),
                    "confidence": r.get("confidence", 1.0),
                    "source": r.get("source", "rule"),
                })
            return ExtractionResult(
                doc_id=doc_id,
                text=clean_text,
                entities=entities,
                triples=triples,
                status="rule_annotated",
                engine="rule_fallback",
                warnings=["Sử dụng bộ bóc tách luật cơ sở do IE model chuyên sâu chưa nạp."],
            )

        from .corpus_pipeline import prepare_clean_document
        from .inference import build_demo_document
        from .preprocess import iter_segments

        demo_doc = build_demo_document(clean_text)
        demo_doc["doc_id"] = doc_id
        segments = list(iter_segments(demo_doc))
        results = self.inner.extract_segments(segments)

        predictions = []
        for source, pred in zip(segments, results):
            pred["doc_start"] = source["doc_start"]
            pred["doc_end"] = source["doc_end"]
            pred["segment_id"] = source.get("segment_id", "seg_0")
            pred["source_text"] = source.get("text", "")
            pred["section"] = source.get("section", "unknown")
            predictions.append(pred)

        clean, prov, warns, stats = prepare_clean_document(demo_doc, predictions)

        return ExtractionResult(
            doc_id=doc_id,
            text=demo_doc["text"],
            entities=clean["entities"],
            triples=clean["triples"],
            status="extracted",
            engine=self.engine,
            provenance=prov,
            quarantined=prov.get("quarantined", []),
            warnings=[f"{k}: {v}" for k, v in warns.items()] if warns else [],
            statistics=stats,
        )

    def type_entity_strings(self, values: list[str], *, document_id: str) -> ExtractionResult:
        """Type each independent string with the joint model; never link list items.

        Bypasses the generative simplifier. Offsets are local to normalized input
        strings and must be interpreted together with input_index, not as TXT offsets.
        """
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError("entities must be a JSON array of non-empty strings")
        if len(values) > 512 or any(len(v) > 1000 for v in values):
            raise ValueError("At most 512 entity strings, each at most 1000 characters")
        texts = [unicodedata.normalize("NFC", v).strip() for v in values]
        from .schema import load_schema
        from .rules import extract_entities, infer_qualifiers
        labels = load_schema().entity_types
        if not texts:
            batches = []
        elif self.inner is None:
            batches = [extract_entities(text, "unknown") for text in texts]
        else:
            import torch
            with torch.inference_mode():
                batches, _ = self.inner.joint_model.inference(
                    texts, labels=sorted(label.casefold() for label in labels),
                    relations=list(self.inner.joint_run.relation_labels),
                    threshold=self.inner.joint_run.entity_threshold,
                    relation_threshold=self.inner.joint_run.relation_threshold,
                    flat_ner=True, batch_size=self.inner.joint_batch_size,
                )
        if len(batches) != len(texts):
            raise RuntimeError("Entity typing returned a different number of input batches")
        entities, outcomes, rejected = [], [], []
        for index, (text, predictions) in enumerate(zip(texts, batches)):
            count = 0
            for prediction in predictions:
                start, end = prediction.get("start"), prediction.get("end")
                label = str(prediction.get("label", "")).upper()
                score = prediction.get("score")
                if (label not in labels or type(start) is not int or type(end) is not int
                        or not 0 <= start < end <= len(text)
                        or (score is not None and (not isinstance(score, (int, float))
                            or isinstance(score, bool) or not math.isfinite(score) or not 0 <= score <= 1))):
                    rejected.append({"input_index": index, "reason": "invalid_entity_prediction"})
                    continue
                entity = {"id": f"E{len(entities) + 1}", "text": text[start:end], "label": label,
                          "start": start, "end": end, "input_index": index,
                          "source": "entity_string_joint_model" if self.inner is not None else "entity_string_rule_fallback"}
                entity["qualifiers"] = infer_qualifiers(text, entity, "unknown")
                if score is not None:
                    entity["score"] = float(score)
                entities.append(entity)
                count += 1
            outcomes.append({"input_index": index, "text": text,
                             "status": "recognized" if count else "unrecognized", "num_entities": count})
        warnings = ["Mỗi chuỗi được nhận diện độc lập; không suy ra quan hệ giữa các mục của mảng."]
        if self.inner is None:
            warnings.append("Entity typing dùng rule_fallback đã được bật tường minh, không phải joint model.")
        if any(outcome["status"] == "unrecognized" for outcome in outcomes):
            warnings.append("Có mục không nhận diện được; xem entity_inputs, không tự gán nhãn mặc định.")
        return ExtractionResult(document_id, "", entities, [], "entity_strings_typed",
                                engine="joint_entity_typing" if self.inner is not None else "rule_fallback",
                                provenance={"entity_inputs": outcomes}, quarantined=rejected, warnings=warnings)

    def extract_file(
        self,
        path: str | Path,
        *,
        document_id: str | None = None,
        encoding: str = "utf-8",
    ) -> ExtractionResult:
        f_path = Path(path).resolve()
        if not f_path.is_file():
            raise FileNotFoundError(f"Medical record file not found: {f_path}")
        text = f_path.read_text(encoding=encoding, errors="replace")
        doc_id = document_id or f_path.stem
        return self.extract_text(text, document_id=doc_id)

    def process_text(
        self,
        text: str,
        *,
        document_id: str = "case_01",
        namespace: str = "case",
    ) -> tuple[ExtractionResult, dict[str, Any]]:
        extraction = self.extract_text(text, document_id=document_id)
        raw_graph = build_case_graph(extraction, namespace=namespace)
        dedup_graph = deduplicate_case_graph(raw_graph, namespace=f"{namespace}_dedup")
        return extraction, dedup_graph


def filter_prediagnosis_text(raw_text: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Filter prediagnosis text using prediagnosis_v2 context policies.

    Removes explicit diagnostic labels, discharge status, and retrospective treatment,
    while preserving explicit legitimate past medical history and clinical symptoms/signs.
    Returns:
        (filtered_text, provenance, warnings)
    """
    from .prediagnosis_v2 import choose_span, context_units
    from .preprocess import normalize_text

    norm = normalize_text(raw_text)
    retrospective_unit = re.compile(
        r"^\s*[-+*•]?\s*(?:chẩn\s*đoán|cđ\b|kết\s*luận|hướng\s*điều\s*trị|phương\s*pháp\s*điều\s*trị|điều\s*trị|ra\s*viện|xuất\s*viện|tổng\s*kết\s*bệnh\s*án)\b",
        re.I,
    )

    kept_units: list[str] = []
    provenance: list[dict[str, Any]] = []
    warnings: list[str] = []

    for u_start, u_end, unit in context_units(norm):
        stripped = unit.strip()
        if not stripped:
            continue
        if retrospective_unit.search(stripped):
            provenance.append({
                "text": stripped,
                "reason": "retrospective_diagnosis_or_discharge_unit",
                "start": u_start,
                "end": u_end,
            })
            continue

        span, reason = choose_span(stripped)
        if span is not None:
            lo, hi = span
            kept_part = stripped[lo:hi].strip()
            if kept_part:
                kept_units.append(kept_part)
            if hi < len(stripped):
                withheld_part = stripped[hi:].strip()
                if withheld_part:
                    provenance.append({
                        "text": withheld_part,
                        "reason": reason,
                        "start": u_start + hi,
                        "end": u_end,
                    })
        else:
            provenance.append({
                "text": stripped,
                "reason": reason,
                "start": u_start,
                "end": u_end,
            })

    filtered_text = "\n".join(kept_units).strip()
    if provenance:
        warnings.append(
            f"Đã loại bỏ {len(provenance)} phân đoạn chẩn đoán/điều trị/ra viện "
            f"theo chính sách prediagnosis_v2 nhằm ngăn ngừa rò rỉ nhãn."
        )

    return filtered_text, provenance, warnings


def _detect_symptom_intent(question: str) -> tuple[str, str]:
    """Classify the single-turn user question intent.

    Only accepts self-reported symptom description queries.
    Rejects general theoretical questions, doc_id lookups, or casual greetings.
    """
    cleaned = normalize(question)

    if len(cleaned) < 5:
        return "insufficient_information", "Câu hỏi quá ngắn để nhận diện triệu chứng."

    # Look up specific case IDs
    if re.search(r"\b(?:doc_\w+|mã\s*(?:bệnh án|hồ sơ|ca bệnh))\b", cleaned):
        return (
            "unsupported_intent",
            "Hệ thống không hỗ trợ tra cứu theo mã hồ sơ/doc_id. Vui lòng mô tả triệu chứng cụ thể.",
        )

    # General knowledge queries
    if re.search(r"^(?:bệnh\s+\w+\s+là gì|nguyên nhân|cách chữa|điều trị|thuốc gì|tại sao bị)", cleaned):
        return (
            "unsupported_intent",
            "Hệ thống chỉ hỗ trợ hỏi bệnh từ mô tả triệu chứng, không trả lời câu hỏi lý thuyết y khoa.",
        )

    # Social chatter
    if re.search(r"^(?:xin chào|chào bạn|hello|hi|bạn là ai|chào buổi sáng)\b", cleaned) and len(cleaned) < 25:
        return (
            "unsupported_intent",
            "Vui lòng mô tả triệu chứng hô hấp bạn đang gặp phải (ví dụ: sốt, ho, khó thở, tức ngực).",
        )

    # Check for presence of specific respiratory symptoms
    specific_respiratory_cues = [
        "ho", "sốt", "khó thở", "thở khò khè", "đau ngực", "tức ngực", "đờm", "khạc đờm",
        "hắt hơi", "sổ mũi", "rát họng", "đau họng", "sp02", "spo2", "thở rít", "ngột ngạt",
        "thở gấp", "ngực", "phổi", "ngạt mũi"
    ]
    found_specific = [cue for cue in specific_respiratory_cues if contains_phrase(cleaned, cue)]
    if not found_specific:
        return (
            "insufficient_information",
            "Chưa nhận diện được triệu chứng hô hấp đặc thù (như ho, sốt, khó thở, đau ngực, khạc đờm...).",
        )

    return "symptom_query", "Mô tả triệu chứng hợp lệ."


class ResearchAssistant:
    """Unified Facade for both symptom query and TXT medical record inputs."""

    def __init__(
        self,
        pipeline: ClinicalPipeline,
        classifier: HybridClassifier | LateFusionClassifier,
        reference_index: ReferenceIndex,
        device: str = "cpu",
        model_versions: dict[str, str] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.classifier = classifier
        self.reference_index = reference_index
        self.device = device
        self.model_versions = model_versions or {
            "ie": "v1.3",
            "classifier": classifier.metadata.get("inference_config", {}).get("method", "hybrid_v1"),
            "reference_index": "train_only_v1",
        }

    @classmethod
    def from_bundles(
        cls,
        ie_bundle: str | Path,
        classifier_bundle: str | Path,
        index_bundle: str | Path,
        *,
        device: str = "auto",
        allow_rule_fallback: bool = False,
    ) -> ResearchAssistant:
        """Instantiate assistant by verifying and loading all three production bundles.

        Fail-closed by default: raises an exception if any bundle manifest, file hash,
        or model loading step fails. Heuristic rule fallback is only used if explicitly
        enabled with allow_rule_fallback=True.
        """
        dev = resolve_device(device)

        # 1. Verify and load IE bundle (fail-closed unless allow_rule_fallback=True)
        v_ie = verify_bundle(ie_bundle, expected_kind="ie")
        if not v_ie.is_valid:
            if not allow_rule_fallback:
                raise ValueError(
                    f"IE bundle verification failed (fail-closed): {v_ie.errors}. "
                    "Rule fallback is disabled by default. Pass allow_rule_fallback=True "
                    "only if you explicitly intend to run the heuristic rule baseline."
                )
            print(f"Cảnh báo IE bundle: {v_ie.errors}", file=sys.stderr)

        pipeline: ClinicalPipeline
        try:
            pipeline = ClinicalPipeline.from_bundle(ie_bundle, device=dev)
        except Exception as exc:
            if not allow_rule_fallback:
                raise RuntimeError(
                    f"Failed to load neural IE pipeline from bundle '{ie_bundle}' (fail-closed): {exc}. "
                    "Set allow_rule_fallback=True if you explicitly intend to run the heuristic rule baseline."
                ) from exc
            pipeline = ClinicalPipeline(device=dev, engine="rule_fallback")

        # 2. Verify and load Classifier bundle (fail-closed)
        v_clf = verify_bundle(classifier_bundle, expected_kind="classifier")
        if not v_clf.is_valid:
            raise ValueError(f"Classifier bundle verification failed (fail-closed): {v_clf.errors}")
        classifier_manifest = json.loads((Path(classifier_bundle) / "bundle.json").read_text(encoding="utf-8"))
        if classifier_manifest.get("classifier_type") == "late_fusion":
            classifier = LateFusionClassifier.from_bundle(classifier_bundle, device=dev)
        else:
            classifier = HybridClassifier.from_bundle(classifier_bundle)

        # 3. Verify and load Reference Index bundle (fail-closed)
        v_idx = verify_bundle(index_bundle, expected_kind="reference_index")
        if not v_idx.is_valid:
            raise ValueError(f"Reference Index bundle verification failed (fail-closed): {v_idx.errors}")
        index = ReferenceIndex.load(index_bundle)

        versions = {
            "ie_bundle": v_ie.version,
            "classifier_bundle": v_clf.version,
            "index_bundle": v_idx.version,
        }

        return cls(
            pipeline=pipeline,
            classifier=classifier,
            reference_index=index,
            device=dev,
            model_versions=versions,
        )

    def analyze_file(
        self,
        path: str | Path,
        *,
        document_id: str | None = None,
        namespace: str = "case",
        image_path: str | Path | None = None,
    ) -> AnalysisResult:
        """Process TXT, optionally with a same-case X-ray and a late-fusion bundle."""
        self._validate_image_input(image_path)
        f_path = Path(path).resolve()
        if not f_path.is_file():
            raise FileNotFoundError(f"File not found: {f_path}")

        raw_text = f_path.read_text(encoding="utf-8", errors="replace")
        return self.analyze_text(raw_text, document_id=document_id or f_path.stem,
                                 namespace=namespace, image_path=image_path, _input_type="medical_record_txt")

    def analyze_text(
        self, text: str, *, document_id: str | None = None, namespace: str = "case",
        image_path: str | Path | None = None, _input_type: str = "medical_record_text",
    ) -> AnalysisResult:
        """Analyze raw medical-record text with the same policy as analyze_file."""
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        self._validate_image_input(image_path)
        raw_text = text
        doc_id = document_id or f"doc_{time.time_ns()}"

        # Filter post-diagnosis text using prediagnosis_v2 context policies
        filtered_text, filter_prov, boundary_warnings = filter_prediagnosis_text(raw_text)

        # Extract entities and triples using grounded corpus pipeline
        extraction = self.pipeline.extract_text(filtered_text, document_id=doc_id)

        # Build and deduplicate graph
        raw_graph = build_case_graph(extraction, namespace=namespace)
        dedup_graph = deduplicate_case_graph(raw_graph, namespace=f"{namespace}_dedup")

        # Classify using Hybrid Classifier
        prediction = self._classify(filtered_text, dedup_graph, image_path=image_path)

        # Retrieve up to 3 similar reference cases
        similar_cases = self.reference_index.find_similar(
            query_graph=dedup_graph,
            query_text=filtered_text,
            top_k=3,
        )

        # Missing information questions
        vitals = extract_retrieval_vitals(filtered_text, dedup_graph)
        missing_questions = []
        if vitals.get("vital_spo2_missing", 1.0) == 1.0:
            missing_questions.append("Bệnh án chưa ghi nhận chỉ số SpO2; cần bổ sung đo bão hòa oxy.")
        if vitals.get(OBSERVED + "temporal_is_acute", 0.0) == 0.0 and vitals.get(OBSERVED + "temporal_is_chronic", 0.0) == 0.0:
            missing_questions.append("Chưa rõ thời gian khởi phát triệu chứng (cấp tính hay mạn tính).")

        warnings = [RESEARCH_DISCLAIMER] + boundary_warnings + prediction.warnings
        if self.reference_index.metadata.get("compatibility_warning"):
            warnings.append(self.reference_index.metadata["compatibility_warning"])

        return AnalysisResult(
            input_type=_input_type,
            document_id=doc_id,
            status=prediction.status,
            schema_version="1.0",
            top5=[c.to_dict() for c in prediction.top5],
            all_scores=prediction.all_scores,
            all_probabilities=prediction.all_probabilities,
            graph=dedup_graph,
            extracted_facts={
                "num_entities": len(extraction.entities),
                "num_triples": len(extraction.triples),
                "entities": extraction.entities,
                "triples": extraction.triples,
            },
            missing_information_questions=missing_questions,
            similar_cases=[s.to_dict() for s in similar_cases],
            model_versions=self.model_versions,
            engine=self.pipeline.engine,
            filter_provenance=filter_prov,
            warnings=warnings,
        )

    def analyze_entities(
        self, entities: list[str], *, document_id: str | None = None,
        namespace: str = "entity_case", image_path: str | Path | None = None,
    ) -> AnalysisResult:
        """Analyze independent entity strings, optionally with a same-case X-ray.

        Graph-only classification: no pseudo-narrative is fed to the text branch.
        Only existing Case→Entity structural rules generate edges. Learned relations
        returned while typing each string are discarded, including within-item ones.
        """
        self._validate_image_input(image_path)
        doc_id = document_id or f"entities_{time.time_ns()}"
        extraction = self.pipeline.type_entity_strings(entities, document_id=doc_id)
        graph = deduplicate_case_graph(build_case_graph(extraction, namespace=namespace),
                                       namespace=f"{namespace}_dedup")
        prediction = self._classify("", graph, image_path=image_path)
        similar = self.reference_index.find_similar(query_graph=graph, query_text="", top_k=3)
        warnings = [RESEARCH_DISCLAIMER, *extraction.warnings, *prediction.warnings,
                    "Đầu vào entity rời rạc thiếu ngữ cảnh/SPO; không dùng nhánh Text và chưa có benchmark chất lượng riêng.",
                    "Chỉ cung cấp thông tin trước chẩn đoán; không truyền nhãn đích/kết luận chẩn đoán vào mảng entity."]
        if self.reference_index.metadata.get("compatibility_warning"):
            warnings.append(self.reference_index.metadata["compatibility_warning"])
        insufficient = prediction.status == "insufficient_information"
        return AnalysisResult(
            input_type="entity_array", document_id=doc_id, status=prediction.status,
            schema_version="1.0", top5=[] if insufficient else [c.to_dict() for c in prediction.top5],
            all_scores={} if insufficient else prediction.all_scores,
            all_probabilities={} if insufficient else prediction.all_probabilities,
            graph=graph, extracted_facts={"input_entities": list(entities),
                "entity_inputs": extraction.provenance["entity_inputs"],
                "num_entities": len(extraction.entities), "num_triples": 0,
                "entities": extraction.entities, "triples": [], "quarantined": extraction.quarantined},
            missing_information_questions=CLINICAL_QUESTIONS_BANK[:3],
            similar_cases=[case.to_dict() for case in similar], model_versions=self.model_versions,
            engine=extraction.engine, warnings=warnings,
        )

    def _validate_image_input(self, image_path: str | Path | None) -> None:
        if image_path is not None:
            if not isinstance(self.classifier, LateFusionClassifier):
                raise ValueError("Ảnh cần classifier-fusion-v1; bộ Text+Graph không nhận ảnh.")
            if not Path(image_path).is_file():
                raise FileNotFoundError(f"X-ray file not found: {image_path}")

    def _classify(self, text: str, graph: dict, *, image_path: str | Path | None = None) -> HybridPrediction:
        self._validate_image_input(image_path)
        if image_path is None:
            return self.classifier.predict(text=text, graph=graph)
        return self.classifier.predict(text=text, graph=graph, image_path=image_path)

    def ask_symptoms(self, question: str, *, image_path: str | Path | None = None) -> QueryAnswer:
        """Process single-turn Vietnamese symptom description question."""
        intent, intent_msg = _detect_symptom_intent(question)

        warnings = [
            RESEARCH_DISCLAIMER,
            "Tính năng hỏi bệnh qua mô tả triệu chứng ngắn là THỬ NGHIỆM; mô hình phân lớp được huấn luyện trên bệnh án đầy đủ.",
        ]

        if intent == "unsupported_intent":
            return QueryAnswer(
                input_type="symptom_query",
                question=question,
                status="unsupported_intent",
                schema_version="1.0",
                top5=[],
                all_scores={},
                all_probabilities={},
                extracted_facts={"entities": [], "triples": []},
                missing_information_questions=CLINICAL_QUESTIONS_BANK[:3],
                similar_cases=[],
                model_versions=self.model_versions,
                engine=self.pipeline.engine,
                warnings=[intent_msg, RESEARCH_DISCLAIMER],
            )

        if intent == "insufficient_information":
            return QueryAnswer(
                input_type="symptom_query",
                question=question,
                status="insufficient_information",
                schema_version="1.0",
                top5=[],
                all_scores={},
                all_probabilities={},
                extracted_facts={"entities": [], "triples": []},
                missing_information_questions=CLINICAL_QUESTIONS_BANK[:4],
                similar_cases=[],
                model_versions=self.model_versions,
                engine=self.pipeline.engine,
                warnings=[intent_msg, "Chưa đủ dữ kiện để tham khảo phân lớp."],
            )

        self._validate_image_input(image_path)
        # Parse symptoms using pipeline
        extraction = self.pipeline.extract_text(question, document_id="query_case")
        raw_graph = build_case_graph(extraction, namespace="query")
        dedup_graph = deduplicate_case_graph(raw_graph, namespace="query_dedup")

        # Run hybrid classification
        prediction = self._classify(question, dedup_graph, image_path=image_path)

        # Query reference index (up to 3 cases)
        similar_cases = self.reference_index.find_similar(
            query_graph=dedup_graph,
            query_text=question,
            top_k=3,
        )

        # Evaluate missing vitals and suggest follow-up questions
        vitals = extract_retrieval_vitals(question, dedup_graph)
        missing_q = []
        if vitals.get("vital_spo2_missing", 1.0) == 1.0:
            missing_q.append("Bạn đã đo chỉ số SpO2 chưa? Đo oxy máu giúp đánh giá mức độ suy hô hấp.")
        if vitals.get(OBSERVED + "vital_fever_present", 0.0) == 0.0:
            missing_q.append("Bạn có bị sốt không? Nhiệt độ cơ thể là bao nhiêu?")
        if vitals.get(OBSERVED + "temporal_is_acute", 0.0) == 0.0 and vitals.get(OBSERVED + "temporal_is_chronic", 0.0) == 0.0:
            missing_q.append("Các triệu chứng trên đã xuất hiện được bao nhiêu ngày?")

        all_warnings = warnings + prediction.warnings
        if self.reference_index.metadata.get("compatibility_warning"):
            all_warnings.append(self.reference_index.metadata["compatibility_warning"])

        return QueryAnswer(
            input_type="symptom_query",
            question=question,
            status="experimental_query",
            schema_version="1.0",
            top5=[c.to_dict() for c in prediction.top5],
            all_scores=prediction.all_scores,
            all_probabilities=prediction.all_probabilities,
            extracted_facts={
                "num_entities": len(extraction.entities),
                "num_triples": len(extraction.triples),
                "entities": extraction.entities,
                "triples": extraction.triples,
            },
            missing_information_questions=missing_q,
            similar_cases=[s.to_dict() for s in similar_cases],
            model_versions=self.model_versions,
            engine=self.pipeline.engine,
            warnings=all_warnings,
        )


def get_runtime_info() -> dict[str, Any]:
    """Retrieve runtime environment, CPU/device availability, memory, and package info."""
    mem = psutil.virtual_memory()
    info = {
        "python_version": sys.version.split()[0],
        "os_system": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "total_ram_gb": round(mem.total / (1024 ** 3), 2),
        "available_ram_gb": round(mem.available / (1024 ** 3), 2),
        "device": resolve_device("auto"),
    }

    info["package_errors"] = {}
    for pkg_name in ("torch", "transformers", "gliner", "lightgbm", "sklearn", "joblib", "yaml", "sentencepiece", "numpy", "scipy", "torchvision", "PIL"):
        try:
            mod = __import__(pkg_name)
            info[f"{pkg_name}_version"] = getattr(mod, "__version__", "installed")
        except Exception as exc:
            info[f"{pkg_name}_version"] = "not_installed"
            info["package_errors"][pkg_name] = f"{type(exc).__name__}: {exc}"

    return info


def doctor(
    ie_bundle: str | Path | None = None,
    classifier_bundle: str | Path | None = None,
    index_bundle: str | Path | None = None,
) -> dict[str, Any]:
    """Diagnose local environment readiness, bundle integrity, and offline configuration."""
    report = {
        "status": "PASS",
        "runtime": get_runtime_info(),
        "bundles": {},
        "recommendations": [],
    }

    required = {"numpy", "scipy", "lightgbm", "sklearn", "joblib", "yaml"}
    if ie_bundle:
        required.update({"torch", "transformers", "gliner", "sentencepiece"})
    for key, path, kind in (("ie_bundle", ie_bundle, "ie"),
                            ("classifier_bundle", classifier_bundle, "classifier"),
                            ("index_bundle", index_bundle, "reference_index")):
        if not path:
            continue
        b_info = verify_bundle(path, expected_kind=kind)
        report["bundles"][key] = b_info.to_dict()
        if not b_info.is_valid:
            report["status"] = "ERROR"
            report["recommendations"].append(f"{key}: {b_info.errors}")
        if key == "classifier_bundle":
            manifest_path = Path(path) / "bundle.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(manifest, dict) and manifest.get("classifier_type") == "late_fusion":
                    required.update({"torch", "torchvision", "PIL"})
                    base_info = verify_bundle(Path(path) / "base", expected_kind="classifier")
                    report["bundles"]["fusion_base"] = base_info.to_dict()
                    if not base_info.is_valid:
                        report["status"] = "ERROR"
                        report["recommendations"].append(f"fusion_base: {base_info.errors}")
            except (OSError, ValueError):
                pass  # Already reported by the bundle verifier.
    if sys.version_info[:2] != (3, 12):
        report["status"] = "ERROR"
        report["recommendations"].append("Supported runtime: Python 3.12")
    for name in sorted(required):
        if report["runtime"].get(f"{name}_version") == "not_installed":
            report["status"] = "ERROR"
            report["recommendations"].append(f"Required dependency unavailable: {name}")
    report["required_dependencies"] = sorted(required)
    report["verification_scope"] = "manifest, required assets, SHA-256, dependency imports; not a model inference smoke test"

    return report
