"""Unified Clinical Knowledge Graph Query Engine & Assistant API."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..classification import LABELS
from ..classification.dataset import ClassificationRecord
from .index import ClinicalGraphIndex
from .matcher import CaseSimilarityMatcher, _extract_graph_elements
from .schema import ClinicalQuery, DiseaseProfile, QueryResult, SimilarCase
from .clinical_context import contains_phrase, normalize_prose, positive_phrase_in_text


class ClinicalQueryEngine:
    """Unified facade for clinical graph retrieval, case-based matching, and cohort profiling."""

    def __init__(self, index: ClinicalGraphIndex | None = None) -> None:
        if index is None:
            self.index = ClinicalGraphIndex.build_or_load()
        else:
            self.index = index
        self.matcher = CaseSimilarityMatcher(self.index)

    def search(self, query: ClinicalQuery | str, max_results: int = 50) -> QueryResult:
        """Execute structured or free-form clinical query over the graph corpus."""
        if isinstance(query, str):
            # Parse simple string query into ClinicalQuery
            c_query = self._parse_string_query(query)
        else:
            c_query = query
        return self.index.query_boolean(c_query, max_results=max_results)

    def find_similar_cases(
        self,
        case: ClassificationRecord | str | dict[str, Any],
        top_k: int = 5,
        restrict_to_label: str | None = None,
    ) -> list[SimilarCase]:
        """Retrieve historically similar patient cases given a record, doc_id, text, or graph."""
        query_graph: dict[str, Any] | None = None
        query_text: str | None = None
        candidate_ids: set[str] | None = None

        if isinstance(case, str):
            if case in self.index.records:
                rec = self.index.records[case]
                query_graph = rec.graph
                query_text = rec.text
            else:
                query_text = case
        elif isinstance(case, ClassificationRecord):
            query_graph = case.graph
            query_text = case.text
        elif isinstance(case, dict):
            query_graph = case
            query_text = str(case.get("text", ""))

        if restrict_to_label and restrict_to_label in self.index.label_index:
            candidate_ids = self.index.label_index[restrict_to_label]

        results = self.matcher.find_similar(
            query_graph=query_graph,
            query_text=query_text,
            candidate_doc_ids=candidate_ids,
            top_k=top_k + int(isinstance(case, str) and case in self.index.records),
        )

        # Remove self if doc_id was in corpus
        if isinstance(case, str) and case in self.index.records:
            results = [r for r in results if r.doc_id != case]
        return results[:top_k]

    def get_disease_profile(self, label: str) -> DiseaseProfile:
        """Extract statistical knowledge profile of a specific disease across the corpus."""
        if label not in self.index.label_index:
            raise ValueError(f"Unknown disease label '{label}'. Valid labels: {list(LABELS)}")

        doc_ids = self.index.label_index[label]
        total_cases = len(doc_ids)

        symptom_counter: Counter[str] = Counter()
        sign_counter: Counter[str] = Counter()
        test_counter: Counter[str] = Counter()
        anatomy_counter: Counter[str] = Counter()
        triple_counter: Counter[str] = Counter()

        hypo_cases = 0
        fever_cases = 0
        chronic_cases = 0
        smoking_cases = 0

        for did in doc_ids:
            rec = self.index.records[did]
            c_set, t_set = self.matcher.cached_elements.get(did, (set(), set()))
            vitals = self.index.doc_vitals_features.get(did, {})

            for c in c_set:
                parts = c.split(":", 1)
                if len(parts) == 2:
                    etype, text = parts[0], parts[1]
                    if etype == "symptom":
                        symptom_counter[text] += 1
                    elif etype == "sign":
                        sign_counter[text] += 1
                    elif etype == "test":
                        test_counter[text] += 1
                    elif etype == "anatomy":
                        anatomy_counter[text] += 1

            for t in t_set:
                triple_counter[t] += 1

            if vitals.get("vital_hypoxemia_severe", 0.0) > 0.5 or vitals.get("vital_hypoxemia_moderate", 0.0) > 0.5:
                hypo_cases += 1
            if vitals.get("vital_fever_high", 0.0) > 0.5 or vitals.get("vital_fever_present", 0.0) > 0.5:
                fever_cases += 1
            if vitals.get("temporal_is_chronic", 0.0) > 0.5:
                chronic_cases += 1
            if vitals.get("risk_smoking", 0.0) > 0.5:
                smoking_cases += 1

        def _to_ranked_list(counter: Counter[str], top_n: int = 8) -> list[tuple[str, int, float]]:
            return [
                (item, count, round(count / total_cases * 100.0, 1))
                for item, count in counter.most_common(top_n)
            ]

        return DiseaseProfile(
            disease_name=label,
            total_cases=total_cases,
            top_symptoms=_to_ranked_list(symptom_counter),
            top_signs=_to_ranked_list(sign_counter),
            top_tests=_to_ranked_list(test_counter),
            top_anatomies=_to_ranked_list(anatomy_counter),
            top_triples=_to_ranked_list(triple_counter),
            spo2_hypoxemia_rate=round(hypo_cases / total_cases * 100.0, 1) if total_cases else 0.0,
            high_fever_rate=round(fever_cases / total_cases * 100.0, 1) if total_cases else 0.0,
            chronic_rate=round(chronic_cases / total_cases * 100.0, 1) if total_cases else 0.0,
            smoking_risk_rate=round(smoking_cases / total_cases * 100.0, 1) if total_cases else 0.0,
        )

    def explain_case_evidence(
        self,
        case: ClassificationRecord | str | dict[str, Any],
        predicted_label: str | None = None,
    ) -> dict[str, Any]:
        """Provide explainable clinical evidence by retrieving matching cases and distinctive hallmarks."""
        if isinstance(case, str) and case in self.index.records:
            rec = self.index.records[case]
        elif isinstance(case, ClassificationRecord):
            rec = case
        else:
            rec = None

        graph = rec.graph if rec else (case if isinstance(case, dict) else {})
        text = rec.text if rec else (case if isinstance(case, str) else "")
        true_label = rec.label if rec else None
        target_label = predicted_label or true_label

        # 1. Distinctive clinical findings in graph
        concepts, triples = _extract_graph_elements(graph)
        vitals = self.index.doc_vitals_features.get(rec.doc_id, {}) if rec else {}

        # 2. Similar historical cases with the same disease
        same_disease_cases = self.find_similar_cases(case, top_k=3, restrict_to_label=target_label)

        # 3. Differential diagnosis counter-cases (different diseases)
        all_similar = self.find_similar_cases(case, top_k=6)
        differential_cases = [c for c in all_similar if c.label != target_label][:2]

        return {
            "query_doc_id": rec.doc_id if rec else "EXTERNAL_QUERY",
            "evaluated_disease": target_label,
            "true_disease": true_label,
            "key_present_concepts": sorted(list(concepts)),
            "key_relational_triples": sorted(list(triples)),
            "vital_signs_summary": {
                "spo2_estimate": vitals.get("vital_spo2_val", 0.98) * 100.0,
                "has_fever": bool(vitals.get("vital_fever_present", 0.0)),
                "is_acute": bool(vitals.get("temporal_is_acute", 0.0)),
                "is_chronic": bool(vitals.get("temporal_is_chronic", 0.0)),
                "smoking_history": bool(vitals.get("risk_smoking", 0.0)),
            },
            "supportive_historical_cases": [
                {
                    "doc_id": c.doc_id,
                    "label": c.label,
                    "similarity": c.similarity_score,
                    "shared_concepts": c.overlapping_concepts,
                    "shared_triples": c.overlapping_triples,
                    "snippet": c.text_snippet,
                }
                for c in same_disease_cases
            ],
            "differential_historical_cases": [
                {
                    "doc_id": c.doc_id,
                    "competing_label": c.label,
                    "similarity": c.similarity_score,
                    "shared_concepts": c.overlapping_concepts,
                    "snippet": c.text_snippet,
                }
                for c in differential_cases
            ],
        }

    def _parse_string_query(self, raw_text: str) -> ClinicalQuery:
        """Heuristically extract clinical entities and criteria from free-text search string."""
        query = ClinicalQuery(text_query=raw_text)
        lower = normalize_prose(raw_text)

        # Check labels
        for lab in LABELS:
            if lab.lower() in lower:
                query.labels.append(lab)

        # SpO2 check
        match_spo2 = re.search(r"spo2\s*([<>]=?|[:=])\s*(\d{2,3})", lower)
        if match_spo2:
            op, val = match_spo2.group(1), float(match_spo2.group(2))
            if "<" in op:
                query.max_spo2 = val
            elif ">" in op:
                query.min_spo2 = val

        # Fever
        if positive_phrase_in_text(lower, "sốt cao"):
            query.fever_high = True
        elif positive_phrase_in_text(lower, "sốt"):
            query.fever_present = True
        elif contains_phrase(lower, "không sốt") or contains_phrase(lower, "không có sốt"):
            query.negated_symptoms.append("sốt")

        # Common symptoms
        candidate_symptoms = ["ho", "khó thở", "đau ngực", "mệt mỏi", "ho ra máu", "khò khè", "đờm"]
        for sym in candidate_symptoms:
            if contains_phrase(lower, sym):
                if contains_phrase(lower, f"không {sym}") or contains_phrase(lower, f"không có {sym}"):
                    query.negated_symptoms.append(sym)
                elif positive_phrase_in_text(lower, sym):
                    query.symptoms.append(sym)

        return query
