"""High-performance in-memory Inverted Clinical Graph Index."""
from __future__ import annotations

import pickle
import re
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..classification.dataset import ClassificationRecord, load_all_splits
from .clinical_context import OBSERVED, canonical_name, contains_phrase, extract_retrieval_vitals, is_current_positive, node_concept
from .schema import ClinicalQuery, QueryResult

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INDEX_CACHE = ROOT / "artifacts" / "cache" / "clinical_graph_index_context_v11.pkl"
INDEX_VERSION = "1.1"


def _norm_str(text: str) -> str:
    cleaned = unicodedata.normalize("NFC", text).strip().casefold()
    return re.sub(r"\s+", " ", cleaned)


class ClinicalGraphIndex:
    """Multi-dimensional Inverted Graph Index over the clinical corpus."""

    def __init__(self) -> None:
        self.evidence_version = INDEX_VERSION
        self.source_splits: tuple[str, ...] = ()
        self.records: dict[str, ClassificationRecord] = {}

        # 1. Concept Inverted Index: key -> set of doc_ids
        # Keys:
        #   "type:text" (e.g. "symptom:ho", "test:spo2")
        #   "type:text:assertion" (e.g. "symptom:ho:present", "symptom:sốt:negated")
        self.concept_index: dict[str, set[str]] = defaultdict(set)

        # 2. Text keyword inverted index: word -> set of doc_ids
        self.word_index: dict[str, set[str]] = defaultdict(set)

        # 3. SPO Triple Inverted Index:
        #   "s_type:s_text--pred-->t_type:t_text"
        #   "pred:predicate_name"
        self.triple_index: dict[str, set[str]] = defaultdict(set)

        # 4. Clinical Vitals & Hallmarks Sets
        self.doc_spo2_val: dict[str, float] = {}
        self.doc_vitals_features: dict[str, dict[str, float]] = {}

        self.idx_hypoxemia_severe: set[str] = set()    # SpO2 < 90%
        self.idx_hypoxemia_moderate: set[str] = set()  # 90% <= SpO2 < 95%
        self.idx_fever_high: set[str] = set()          # Temp >= 38.5C
        self.idx_fever_present: set[str] = set()       # Any fever
        self.idx_temporal_acute: set[str] = set()      # Duration <= 7 days
        self.idx_temporal_chronic: set[str] = set()    # Duration > 21 days
        self.idx_risk_smoking: set[str] = set()
        self.idx_hallmark_effusion: set[str] = set()
        self.idx_hallmark_pneumothorax: set[str] = set()
        self.idx_hallmark_edema: set[str] = set()

        # 5. Diagnostic label index: label -> set of doc_ids
        self.label_index: dict[str, set[str]] = defaultdict(set)

    def add_record(self, rec: ClassificationRecord) -> None:
        """Index a single clinical case graph and prediagnosis context."""
        doc_id = rec.doc_id
        self.records[doc_id] = rec
        self.label_index[rec.label].add(doc_id)

        # A. Index Words from Text
        if rec.text:
            norm_text = _norm_str(rec.text)
            words = set(re.findall(r"\b\w+\b", norm_text))
            for w in words:
                self.word_index[w].add(doc_id)

        # B. Index Graph Nodes & Concepts
        graph = rec.graph or {}
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        node_map: dict[str, dict[str, Any]] = {}

        for node in nodes:
            uid = node.get("uid")
            if uid:
                node_map[uid] = node

            if node.get("kind") == "Entity":
                props = node.get("properties", {})
                etype = _norm_str(str(props.get("entity_type", "unknown")))
                text = node_concept(node).split(":", 1)[-1]
                assertion = _norm_str(str(props.get("assertion", "present")))
                temporality = _norm_str(str(props.get("temporality", "current")))

                if text:
                    self.concept_index[f"{etype}:{text}"].add(doc_id)
                    self.concept_index[f"{etype}:{text}:{assertion}"].add(doc_id)
                    self.concept_index[f"{etype}:{text}:{assertion}:{temporality}"].add(doc_id)

        # C. Index Graph Edges (Triples)
        for edge in edges:
            s_node = node_map.get(edge.get("source"), {})
            t_node = node_map.get(edge.get("target"), {})
            if not all(is_current_positive(item) for item in (edge, s_node, t_node)):
                continue
            pred = _norm_str(str(edge.get("predicate", "unknown")))
            self.triple_index[f"pred:{pred}"].add(doc_id)

            if s_node.get("kind") == "Entity" and t_node.get("kind") == "Entity":
                s_props = s_node.get("properties", {})
                t_props = t_node.get("properties", {})

                s_type = _norm_str(str(s_props.get("entity_type", "")))
                s_text = node_concept(s_node).split(":", 1)[-1]
                t_type = _norm_str(str(t_props.get("entity_type", "")))
                t_text = node_concept(t_node).split(":", 1)[-1]

                if s_text and t_text:
                    full_triple = f"{s_type}:{s_text}--{pred}-->{t_type}:{t_text}"
                    self.triple_index[full_triple].add(doc_id)
                    abstract_triple = f"{s_type}--{pred}-->{t_type}"
                    self.triple_index[abstract_triple].add(doc_id)

        # D. Index Clinical Vitals & Hallmarks
        vitals = extract_retrieval_vitals(rec.text or "", rec.graph)
        self.doc_vitals_features[doc_id] = vitals

        # Recover actual SpO2 estimate: vitals['vital_spo2_val'] * 100.0
        if vitals.get("vital_spo2_missing", 1.0) == 0.0:
            self.doc_spo2_val[doc_id] = vitals["vital_spo2_val"] * 100.0

        if vitals.get("vital_hypoxemia_severe", 0.0) > 0.5:
            self.idx_hypoxemia_severe.add(doc_id)
        if vitals.get("vital_hypoxemia_moderate", 0.0) > 0.5:
            self.idx_hypoxemia_moderate.add(doc_id)
        if vitals.get("vital_fever_high", 0.0) > 0.5:
            self.idx_fever_high.add(doc_id)
        if vitals.get("vital_fever_present", 0.0) > 0.5:
            self.idx_fever_present.add(doc_id)
        if vitals.get("temporal_is_acute", 0.0) > 0.5:
            self.idx_temporal_acute.add(doc_id)
        if vitals.get("temporal_is_chronic", 0.0) > 0.5:
            self.idx_temporal_chronic.add(doc_id)
        if vitals.get("risk_smoking", 0.0) > 0.5:
            self.idx_risk_smoking.add(doc_id)
        if vitals.get("sign_effusion_hallmark", 0.0) > 0.5:
            self.idx_hallmark_effusion.add(doc_id)
        if vitals.get("sign_pneumothorax_hallmark", 0.0) > 0.5:
            self.idx_hallmark_pneumothorax.add(doc_id)
        if vitals.get("sign_pulmonary_edema_hallmark", 0.0) > 0.5:
            self.idx_hallmark_edema.add(doc_id)

    def search_concept(
        self,
        entity_type: str,
        text: str,
        assertion: str = "present",
        strict_assertion: bool = True,
        temporality: str | None = None,
    ) -> set[str]:
        """Search cases containing an entity concept."""
        e_type = _norm_str(entity_type)
        e_text = canonical_name(e_type, text)
        assert_val = _norm_str(assertion)
        temporal_val = _norm_str(temporality) if temporality is not None else None
        if not e_text:
            return set()

        if strict_assertion:
            key = f"{e_type}:{e_text}:{assert_val}"
            if temporal_val is not None:
                key += f":{temporal_val}"
            if key in self.concept_index:
                return set(self.concept_index[key])
        else:
            key = f"{e_type}:{e_text}"
            if temporal_val is None and key in self.concept_index:
                return set(self.concept_index[key])

        # Partial phrase fallback if exact concept not matched
        matches = set()
        prefix = f"{e_type}:"
        for c_key, ids in self.concept_index.items():
            parts = c_key.split(":")
            if not c_key.startswith(prefix) or not contains_phrase(parts[1], e_text):
                continue
            if strict_assertion and (len(parts) < 3 or parts[2] != assert_val):
                continue
            if temporal_val is not None and (len(parts) < 4 or parts[3] != temporal_val):
                continue
            matches.update(ids)
        return matches

    def search_text_phrase(self, phrase: str) -> set[str]:
        """Search cases containing all words in a phrase."""
        norm = _norm_str(phrase)
        words = re.findall(r"\b\w+\b", norm)
        if not words:
            return set(self.records.keys())

        result: set[str] | None = None
        for w in words:
            matching_ids = self.word_index.get(w, set())
            result = matching_ids if result is None else result.intersection(matching_ids)
        return result or set()

    def query_boolean(self, query: ClinicalQuery, max_results: int = 50) -> QueryResult:
        """Execute complex multi-criteria clinical query using boolean set operations."""
        t_start = time.perf_counter()
        all_doc_ids = set(self.records.keys())
        positive_sets: list[set[str]] = []

        # 1. Symptoms
        for sym in query.symptoms:
            matches = self.search_concept("symptom", sym, assertion="present", temporality="current")
            positive_sets.append(matches)

        for n_sym in query.negated_symptoms:
            matches = self.search_concept("symptom", n_sym, assertion="negated", temporality="current")
            positive_sets.append(matches)

        # 2. Signs
        for sign in query.signs:
            matches = self.search_concept("sign", sign, assertion="present", temporality="current")
            positive_sets.append(matches)

        for n_sign in query.negated_signs:
            matches = self.search_concept("sign", n_sign, assertion="negated", temporality="current")
            positive_sets.append(matches)

        # 3. Other declared entity filters use the same confirmed/current policy.
        for etype, values in (("test", query.tests), ("anatomy", query.anatomies),
                              ("condition", query.conditions), ("treatment", query.treatments)):
            for value in values:
                positive_sets.append(self.search_concept(etype, value, temporality="current"))

        # 4. Vitals & Temporal
        if query.min_spo2 is not None or query.max_spo2 is not None:
            min_s = query.min_spo2 if query.min_spo2 is not None else 0.0
            max_s = query.max_spo2 if query.max_spo2 is not None else 100.0
            spo2_matches = {
                did for did, s_val in self.doc_spo2_val.items() if min_s <= s_val <= max_s
            }
            positive_sets.append(spo2_matches)

        for expected, key in (
            (query.fever_high, "vital_fever_high"), (query.fever_present, "vital_fever_present"),
            (query.is_acute, "temporal_is_acute"), (query.is_chronic, "temporal_is_chronic"),
            (query.smoking_risk, "risk_smoking"), (query.has_effusion_hallmark, "sign_effusion_hallmark"),
            (query.has_pneumothorax_hallmark, "sign_pneumothorax_hallmark"),
            (query.has_edema_hallmark, "sign_pulmonary_edema_hallmark"),
        ):
            if expected is not None:
                # False means explicitly observed absence, not a default zero.
                positive_sets.append({
                    did for did, values in self.doc_vitals_features.items()
                    if values.get(OBSERVED + key, 0.0) and bool(values.get(key, 0.0)) == expected
                })

        # 6. Labels
        if query.labels:
            label_matches = set()
            for lab in query.labels:
                label_matches.update(self.label_index.get(lab, set()))
            positive_sets.append(label_matches)

        # 7. Text Query
        if query.text_query:
            positive_sets.append(self.search_text_phrase(query.text_query))

        # Combine positive sets
        if not positive_sets:
            candidates = set(all_doc_ids)
        elif query.match_mode.upper() == "OR":
            candidates = set.union(*positive_sets)
        else:  # "AND"
            candidates = set.intersection(*positive_sets)

        # Statistics & Distribution
        matching_ids = sorted(candidates)
        total_matches = len(matching_ids)

        label_counts = Counter(self.records[did].label for did in matching_ids)
        label_percentages = {
            lab: round(cnt / total_matches * 100.0, 2) if total_matches > 0 else 0.0
            for lab, cnt in label_counts.most_common()
        }

        # Samples
        samples = []
        for did in matching_ids[:max_results]:
            rec = self.records[did]
            samples.append({
                "doc_id": did,
                "label": rec.label,
                "spo2": self.doc_spo2_val.get(did),
                "text_snippet": rec.text[:150] + "..." if rec.text else "",
                "num_entities": len(rec.graph.get("nodes", [])),
            })

        duration_ms = round((time.perf_counter() - t_start) * 1000.0, 2)

        return QueryResult(
            query=query,
            total_matches=total_matches,
            matching_doc_ids=matching_ids,
            sample_records=samples,
            label_distribution=dict(label_counts),
            label_percentages=label_percentages,
            execution_time_ms=duration_ms,
        )

    @classmethod
    def build_or_load(
        cls,
        cache_path: Path = DEFAULT_INDEX_CACHE,
        force_rebuild: bool = False,
        splits: tuple[str, ...] = ("train",),
    ) -> ClinicalGraphIndex:
        """Train-only by default; all-split cohort analysis requires explicit splits.

        Version/split-aware cache prevents reusing legacy all-split or unsafe
        assertion/vitals indexes for reference retrieval.
        """
        if not splits or any(s not in {"train", "validation", "test"} for s in splits):
            raise ValueError("splits must be a nonempty tuple of train/validation/test")
        if cache_path.is_file() and not force_rebuild:
            t0 = time.time()
            try:
                with cache_path.open("rb") as handle:
                    instance = pickle.load(handle)
                if getattr(instance, "evidence_version", None) != INDEX_VERSION or getattr(instance, "source_splits", ()) != splits:
                    raise ValueError("Cache evidence version or split policy mismatch")
                print(f"Loaded ClinicalGraphIndex ({len(instance.records)} cases) from: {cache_path} ({round(time.time() - t0, 2)}s)")
                return instance
            except Exception as err:
                print(f"Failed to load cache ({err}), rebuilding index...")

        print(f"Building ClinicalGraphIndex from splits: {splits}...")
        t0 = time.time()
        split_records = load_all_splits()
        instance = cls()
        instance.source_splits = splits

        for split_name in splits:
            for rec in split_records[split_name]:
                instance.add_record(rec)

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("wb") as handle:
            pickle.dump(instance, handle, protocol=pickle.HIGHEST_PROTOCOL)

        print(f"Built & cached ClinicalGraphIndex ({len(instance.records)} cases) in {round(time.time() - t0, 2)}s -> {cache_path}")
        return instance
