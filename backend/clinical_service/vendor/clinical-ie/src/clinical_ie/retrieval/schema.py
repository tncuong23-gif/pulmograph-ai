"""Data schemas and query specifications for Clinical Graph Retrieval."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClinicalQuery:
    """Clinical multi-criteria query specification for structured graph search."""

    # 1. Entity concept filters (list of strings or dict with assertion)
    symptoms: list[str] = field(default_factory=list)
    signs: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    anatomies: list[str] = field(default_factory=list)
    treatments: list[str] = field(default_factory=list)

    # Explicitly documented negation (NEGATED + CURRENT), not an absent mention.
    negated_symptoms: list[str] = field(default_factory=list)
    negated_signs: list[str] = field(default_factory=list)

    # 2. Vital signs and temporal filters
    min_spo2: float | None = None
    max_spo2: float | None = None
    fever_high: bool | None = None       # Temp >= 38.5C
    fever_present: bool | None = None    # Any fever
    is_acute: bool | None = None         # Duration <= 7 days
    is_chronic: bool | None = None       # Duration > 21 days or chronic cue
    smoking_risk: bool | None = None     # History of smoking

    # 3. Hallmark syndromes (e.g. effusion, pneumothorax, pulmonary edema)
    has_effusion_hallmark: bool | None = None
    has_pneumothorax_hallmark: bool | None = None
    has_edema_hallmark: bool | None = None

    # 4. Target diagnosis labels filter (e.g. ['COPD', 'Hen'])
    labels: list[str] = field(default_factory=list)

    # 5. Free-text keyword search
    text_query: str | None = None

    # Matching mode: "AND" (strict intersection) or "OR" (union with ranking)
    match_mode: str = "AND"


@dataclass
class QueryResult:
    """Result container for structured clinical graph queries."""

    query: ClinicalQuery | str
    total_matches: int
    matching_doc_ids: list[str]
    sample_records: list[dict[str, Any]]
    label_distribution: dict[str, int]
    label_percentages: dict[str, float]
    execution_time_ms: float


@dataclass
class SimilarCase:
    """A historically similar clinical patient case retrieved via graph matching."""

    doc_id: str
    label: str
    similarity_score: float
    graph_similarity: float
    semantic_similarity: float
    vitals_similarity: float
    overlapping_concepts: list[str]
    overlapping_triples: list[str]
    text_snippet: str
    full_graph: dict[str, Any] | None = None


@dataclass
class DiseaseProfile:
    """Statistical knowledge summary of a specific respiratory disease in the corpus."""

    disease_name: str
    total_cases: int
    top_symptoms: list[tuple[str, int, float]]   # (symptom, count, percentage)
    top_signs: list[tuple[str, int, float]]      # (sign, count, percentage)
    top_tests: list[tuple[str, int, float]]      # (test, count, percentage)
    top_anatomies: list[tuple[str, int, float]]  # (anatomy, count, percentage)
    top_triples: list[tuple[str, int, float]]    # (SPO triple, count, percentage)
    spo2_hypoxemia_rate: float
    high_fever_rate: float
    chronic_rate: float
    smoking_risk_rate: float
