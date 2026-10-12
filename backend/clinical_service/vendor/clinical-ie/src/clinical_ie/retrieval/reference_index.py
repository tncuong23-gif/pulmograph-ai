"""Fixed, de-identified Reference Case Index for symptom and clinical case retrieval.

Policy:
- Train-only source: strictly forbids validation or test split records.
- De-identified safe IDs (e.g. REF_xxxx).
- Synthesized non-verbatim case summaries (no raw medical record text stored or returned).
- Top-K <= 3: never pad with random cases if matching cases are fewer than 3.
- Similarity scores are reference alignment metrics, NOT diagnostic probabilities.
"""
from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .clinical_context import (
    canonical_name, extract_retrieval_vitals, graph_elements, normalize,
    normalize_vitals, text_concepts, vitals_similarity,
)

DISCLAIMER_SIMILARITY = (
    "Điểm tương đồng phản ánh mức độ trùng khớp đặc trưng đồ thị và chỉ số lâm sàng "
    "với ca tham chiếu; không phải xác suất chẩn đoán và không làm thay đổi điểm phân lớp."
)


def _norm(text: str) -> str:
    return normalize(text)


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


@dataclass(frozen=True)
class SimilarCaseSummary:
    ref_id: str
    label: str
    similarity_score: float
    graph_similarity: float
    vitals_similarity: float
    shared_concepts: list[str]
    shared_triples: list[str]
    deidentified_summary: str
    warning: str = DISCLAIMER_SIMILARITY

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "label": self.label,
            "similarity_score": round(self.similarity_score, 4),
            "graph_similarity": round(self.graph_similarity, 4),
            "vitals_similarity": round(self.vitals_similarity, 4),
            "shared_concepts": self.shared_concepts,
            "shared_triples": self.shared_triples,
            "deidentified_summary": self.deidentified_summary,
            "warning": self.warning,
        }


@dataclass
class ReferenceCase:
    ref_id: str
    label: str
    concepts: set[str]
    triples: set[str]
    vitals: dict[str, float]
    summary_text: str

    def __post_init__(self) -> None:
        self.concepts = {
            f"{_norm(etype)}:{canonical_name(etype, name)}"
            for concept in self.concepts if ":" in concept
            for etype, name in [concept.split(":", 1)]
        }
        self.triples = {_norm(triple) for triple in self.triples}
        self.vitals = normalize_vitals(self.vitals)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "label": self.label,
            "concepts": sorted(self.concepts),
            "triples": sorted(self.triples),
            # Preserve measured/negative zero values AND their observation masks.
            "vitals": {k: round(v, 4) for k, v in self.vitals.items()},
            "summary_text": self.summary_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReferenceCase:
        return cls(
            ref_id=str(data["ref_id"]),
            label=str(data["label"]),
            concepts=set(data.get("concepts", [])),
            triples=set(data.get("triples", [])),
            vitals=dict(data.get("vitals", {})),
            summary_text=str(data.get("summary_text", "")),
        )


def _extract_graph_concepts_and_triples(graph: dict[str, Any] | None) -> tuple[set[str], set[str]]:
    return graph_elements(graph)


def build_deidentified_summary(
    label: str,
    concepts: set[str],
    vitals: dict[str, float],
) -> str:
    """Synthesize a clinical summary from extracted concepts and vitals without verbatim copying."""
    symptoms = [c.split(":", 1)[1] for c in sorted(concepts) if c.startswith("symptom:")]
    signs = [c.split(":", 1)[1] for c in sorted(concepts) if c.startswith("sign:")]
    conditions = [c.split(":", 1)[1] for c in sorted(concepts) if c.startswith("condition:")]

    parts = [f"Ca tham chiếu ({label}):"]

    if symptoms:
        parts.append(f"Triệu chứng ghi nhận gồm {', '.join(symptoms[:5])}.")
    if signs:
        parts.append(f"Dấu hiệu thực thể: {', '.join(signs[:4])}.")
    if conditions:
        parts.append(f"Bệnh lý/hội chứng liên quan: {', '.join(conditions[:3])}.")

    spo2_val = vitals.get("vital_spo2_val", 0.0) * 100.0
    vitals_parts = []
    if spo2_val > 0 and vitals.get("vital_spo2_missing", 1.0) == 0.0:
        vitals_parts.append(f"SpO2 ~{spo2_val:.0f}%")
    if vitals.get("vital_fever_high", 0.0) > 0.5:
        vitals_parts.append("sốt cao")
    elif vitals.get("vital_fever_present", 0.0) > 0.5:
        vitals_parts.append("có sốt")

    if vitals.get("temporal_is_acute", 0.0) > 0.5:
        vitals_parts.append("khởi phát cấp tính")
    elif vitals.get("temporal_is_chronic", 0.0) > 0.5:
        vitals_parts.append("diễn tiến mạn tính")

    if vitals_parts:
        parts.append(f"Chỉ số: {', '.join(vitals_parts)}.")

    return " ".join(parts)


class ReferenceIndex:
    """Fixed reference index loaded strictly from training/approved reference cases."""

    def __init__(self, cases: list[ReferenceCase], metadata: dict[str, Any] | None = None) -> None:
        self.cases = cases
        self.metadata = metadata or {}
        # Pre-index concept inverted index for fast candidate retrieval
        self.concept_to_cases: dict[str, list[int]] = {}
        for idx, c in enumerate(self.cases):
            for concept in c.concepts:
                if concept not in self.concept_to_cases:
                    self.concept_to_cases[concept] = []
                self.concept_to_cases[concept].append(idx)

    def find_similar(
        self,
        query_graph: dict[str, Any] | None = None,
        query_text: str | None = None,
        *,
        top_k: int = 3,
        min_similarity: float = 0.08,
    ) -> list[SimilarCaseSummary]:
        """Find up to top_k similar reference cases.

        If fewer than top_k cases meet the minimum threshold, returns fewer!
        NEVER pads with random cases.
        """
        q_concepts, q_triples = _extract_graph_concepts_and_triples(query_graph)
        if top_k <= 0:
            return []
        if not 0.0 <= min_similarity <= 1.0:
            raise ValueError("min_similarity must be between 0 and 1")
        q_vitals = extract_retrieval_vitals(query_text or "", query_graph)

        if not q_concepts and not q_triples and not query_text:
            return []

        # Find candidates with at least 1 overlapping concept
        candidate_indices: set[int] = set()
        for c in q_concepts:
            if c in self.concept_to_cases:
                candidate_indices.update(self.concept_to_cases[c])

        # If no concept match, fallback to candidate search by top clinical signs/symptoms in text
        has_entities = any(n.get("kind") == "Entity" for n in (query_graph or {}).get("nodes", []))
        if not candidate_indices and query_text and not has_entities:
            # Do not re-introduce a negated/history/uncertain graph finding via text.
            q_concepts = text_concepts(query_text, self.concept_to_cases)
            for concept in q_concepts:
                candidate_indices.update(self.concept_to_cases[concept])

        if not candidate_indices:
            # Strictly return empty list; do NOT pad with arbitrary cases!
            return []

        scored: list[SimilarCaseSummary] = []
        for idx in candidate_indices:
            ref = self.cases[idx]

            # 1. Graph Jaccard overlap
            overlap_c = q_concepts.intersection(ref.concepts)
            overlap_t = q_triples.intersection(ref.triples)

            union_c = q_concepts.union(ref.concepts)
            union_t = q_triples.union(ref.triples)

            jaccard_c = len(overlap_c) / len(union_c) if union_c else 0.0
            jaccard_t = len(overlap_t) / len(union_t) if union_t else 0.0
            graph_sim = 0.75 * jaccard_c + 0.25 * jaccard_t

            # 2. Same clinical similarity components, using observed evidence only.
            vitals_sim = vitals_similarity(q_vitals, ref.vitals)

            # Composite similarity
            composite_sim = 0.65 * graph_sim + 0.35 * vitals_sim

            if composite_sim >= min_similarity:
                scored.append(
                    SimilarCaseSummary(
                        ref_id=ref.ref_id,
                        label=ref.label,
                        similarity_score=composite_sim,
                        graph_similarity=graph_sim,
                        vitals_similarity=vitals_sim,
                        shared_concepts=sorted(list(overlap_c)),
                        shared_triples=sorted(list(overlap_t)),
                        deidentified_summary=ref.summary_text,
                    )
                )

        scored.sort(key=lambda s: (-s.similarity_score, s.ref_id))
        # Cap at requested top_k (max 3 by requirement)
        return scored[:min(top_k, 3)]

    def save_bundle(self, bundle_dir: Path | str) -> dict[str, Any]:
        """Save reference index bundle with manifest and SHA-256."""
        out = Path(bundle_dir)
        out.mkdir(parents=True, exist_ok=True)

        data_file = out / "reference_cases.jsonl"
        with data_file.open("w", encoding="utf-8") as handle:
            for case in self.cases:
                handle.write(json.dumps(case.to_dict(), ensure_ascii=False) + "\n")

        manifest = {
            "schema_version": "1.1",
            "bundle_name": out.name,
            "split": "train_only",
            "policy": "deidentified_non_verbatim_summaries",
            "case_count": len(self.cases),
            "files": {
                "reference_cases.jsonl": _sha256_file(data_file),
            },
            "metadata": self.metadata,
        }

        with (out / "manifest.json").open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)

        return manifest

    @classmethod
    def load(cls, bundle_dir: Path | str) -> ReferenceIndex:
        """Load and verify a reference index bundle."""
        b_dir = Path(bundle_dir)
        manifest_file = b_dir / "manifest.json"
        if not manifest_file.is_file():
            raise FileNotFoundError(f"Missing reference index manifest: {manifest_file}")

        with manifest_file.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)

        if manifest.get("split") != "train_only":
            raise ValueError(f"Reference index must be train_only, got: {manifest.get('split')}")

        data_file = b_dir / "reference_cases.jsonl"
        if not data_file.is_file():
            raise FileNotFoundError(f"Missing reference cases file: {data_file}")

        expected_hash = manifest.get("files", {}).get("reference_cases.jsonl")
        if expected_hash:
            actual_hash = _sha256_file(data_file)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"Checksum mismatch for reference_cases.jsonl: "
                    f"expected {expected_hash}, got {actual_hash}"
                )

        cases: list[ReferenceCase] = []
        with data_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    cases.append(ReferenceCase.from_dict(json.loads(line)))

        metadata = dict(manifest.get("metadata", {}))
        if metadata.get("retrieval_evidence_version") != "1.1":
            message = (
                "Legacy reference bundle: assertion/temporality cannot be recovered "
                "from serialized concepts. Rebuild the train-only index with "
                "scripts/build_reference_index_bundle.py into a NEW directory."
            )
            warnings.warn(message, UserWarning, stacklevel=2)
            metadata["compatibility_warning"] = message
        return cls(cases=cases, metadata=metadata)
