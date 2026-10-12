"""Graph feature extractor for tabular / tree-based classification."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import sparse

from .clinical_features import CLINICAL_FEATURE_NAMES, extract_clinical_vital_features
from .dataset import ClassificationRecord


def _normalize_text(text: str) -> str:
    cleaned = unicodedata.normalize("NFC", text).strip().casefold()
    return re.sub(r"\s+", " ", cleaned)


@dataclass
class GraphFeatureExtractor:
    """Extracts Bag-of-Concepts, Bag-of-SPO, graph statistics, and clinical vitals into sparse features."""

    min_df: int = 2
    binary: bool = False
    include_spo: bool = True
    include_stats: bool = True
    include_clinical_vitals: bool = True

    feature_to_idx: dict[str, int] | None = None
    idx_to_feature: list[str] | None = None
    stat_feature_names: list[str] | None = None
    clinical_feature_names: list[str] | None = None

    def _extract_document_features(self, graph: dict[str, Any]) -> tuple[Counter[str], dict[str, float]]:
        """Extract categorical sparse counts and numeric scalar stats from a single graph."""
        sparse_counts: Counter[str] = Counter()
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        # Node index by UID
        node_by_uid: dict[str, dict[str, Any]] = {}
        entity_nodes: list[dict[str, Any]] = []

        type_counts: Counter[str] = Counter()
        assertion_counts: Counter[str] = Counter()
        temporality_counts: Counter[str] = Counter()

        for node in nodes:
            uid = node.get("uid")
            if uid:
                node_by_uid[uid] = node
            if node.get("kind") == "Entity":
                entity_nodes.append(node)
                props = node.get("properties", {})
                etype = str(props.get("entity_type", "UNKNOWN")).upper()
                text = _normalize_text(str(props.get("text", "")))
                assertion = str(props.get("assertion", "PRESENT")).upper()
                temporality = str(props.get("temporality", "CURRENT")).upper()

                type_counts[etype] += 1
                assertion_counts[assertion] += 1
                temporality_counts[temporality] += 1

                if text:
                    # 1. Detailed concept key
                    sparse_counts[f"concept:{etype}:{text}:{assertion}:{temporality}"] += 1
                    # 2. General finding key (assertion only)
                    sparse_counts[f"finding:{text}:{assertion}"] += 1
                    # 3. Type-text pair
                    sparse_counts[f"type_text:{etype}:{text}"] += 1

        # Edge features
        learned_edge_count = 0
        predicate_counts: Counter[str] = Counter()

        if self.include_spo:
            for edge in edges:
                predicate = str(edge.get("predicate", "UNKNOWN")).upper()
                source_uid = edge.get("source")
                target_uid = edge.get("target")

                source_node = node_by_uid.get(source_uid, {})
                target_node = node_by_uid.get(target_uid, {})

                source_kind = source_node.get("kind")
                target_kind = target_node.get("kind")

                source_props = source_node.get("properties", {})
                target_props = target_node.get("properties", {})

                predicate_counts[predicate] += 1
                sparse_counts[f"pred:{predicate}"] += 1

                if source_kind == "Case":
                    # Case -> Entity derived relation
                    t_text = _normalize_text(str(target_props.get("text", "")))
                    t_type = str(target_props.get("entity_type", "")).upper()
                    t_assert = str(target_props.get("assertion", "PRESENT")).upper()
                    sparse_counts[f"case_edge:{predicate}:{t_type}:{t_text}:{t_assert}"] += 1
                elif source_kind == "Entity" and target_kind == "Entity":
                    learned_edge_count += 1
                    s_text = _normalize_text(str(source_props.get("text", "")))
                    s_type = str(source_props.get("entity_type", "")).upper()
                    t_text = _normalize_text(str(target_props.get("text", "")))
                    t_type = str(target_props.get("entity_type", "")).upper()

                    if s_text and t_text:
                        sparse_counts[f"spo:{s_type}:{s_text}--{predicate}-->{t_type}:{t_text}"] += 1
                        sparse_counts[f"spo_abstract:{s_type}--{predicate}-->{t_type}"] += 1

        stats: dict[str, float] = {}
        if self.include_stats:
            num_entities = len(entity_nodes)
            stats["stat:total_entities"] = float(num_entities)
            stats["stat:is_empty_graph"] = 1.0 if num_entities == 0 else 0.0
            stats["stat:num_symptoms"] = float(type_counts["SYMPTOM"])
            stats["stat:num_signs"] = float(type_counts["SIGN"])
            stats["stat:num_conditions"] = float(type_counts["CONDITION"])
            stats["stat:num_tests"] = float(type_counts["TEST"])
            stats["stat:num_results"] = float(type_counts["RESULT"])
            stats["stat:num_anatomy"] = float(type_counts["ANATOMY"])
            stats["stat:num_treatments"] = float(type_counts["TREATMENT"])
            stats["stat:num_time"] = float(type_counts["TIME"])
            stats["stat:num_negated"] = float(assertion_counts["NEGATED"])
            stats["stat:num_possible"] = float(assertion_counts["POSSIBLE"])
            stats["stat:num_history"] = float(temporality_counts["HISTORY"])
            stats["stat:total_edges"] = float(len(edges))
            stats["stat:learned_edges"] = float(learned_edge_count)

        return sparse_counts, stats

    def fit(self, records: list[ClassificationRecord]) -> GraphFeatureExtractor:
        """Fit vocabulary on training records using min_df threshold."""
        doc_freq: Counter[str] = Counter()
        stat_names: set[str] = set()

        for rec in records:
            counts, stats = self._extract_document_features(rec.graph)
            for feat in counts.keys():
                doc_freq[feat] += 1
            stat_names.update(stats.keys())

        # Filter by min_df
        selected_features = sorted(
            feat for feat, freq in doc_freq.items() if freq >= self.min_df
        )

        self.feature_to_idx = {feat: idx for idx, feat in enumerate(selected_features)}
        self.idx_to_feature = selected_features
        self.stat_feature_names = sorted(stat_names) if self.include_stats else []
        self.clinical_feature_names = list(CLINICAL_FEATURE_NAMES) if self.include_clinical_vitals else []

        return self

    def transform(self, records: list[ClassificationRecord]) -> sparse.csr_matrix:
        """Transform records into a sparse CSR feature matrix."""
        if self.feature_to_idx is None or self.idx_to_feature is None:
            raise RuntimeError("GraphFeatureExtractor must be fitted before transform.")

        num_records = len(records)
        num_vocab = len(self.feature_to_idx)
        num_stats = len(self.stat_feature_names or [])
        num_vitals = len(self.clinical_feature_names or [])
        num_features = num_vocab + num_stats + num_vitals

        rows: list[int] = []
        cols: list[int] = []
        data: list[float] = []

        stat_offset = num_vocab
        vitals_offset = num_vocab + num_stats

        for row_idx, rec in enumerate(records):
            counts, stats = self._extract_document_features(rec.graph)

            # 1. Sparse categorical concept & SPO features
            for feat, count in counts.items():
                col_idx = self.feature_to_idx.get(feat)
                if col_idx is not None:
                    rows.append(row_idx)
                    cols.append(col_idx)
                    val = 1.0 if self.binary else math.log1p(count)
                    data.append(val)

            # 2. Numeric graph stats
            if self.include_stats and self.stat_feature_names:
                for stat_idx, stat_name in enumerate(self.stat_feature_names):
                    val = stats.get(stat_name, 0.0)
                    if val != 0.0:
                        rows.append(row_idx)
                        cols.append(stat_offset + stat_idx)
                        data.append(val)

            # 3. Clinical vitals, temporal cues, and hallmarks
            if self.include_clinical_vitals and self.clinical_feature_names:
                vitals = extract_clinical_vital_features(rec.text or "", rec.graph)
                for v_idx, v_name in enumerate(self.clinical_feature_names):
                    v_val = vitals.get(v_name, 0.0)
                    if v_val != 0.0:
                        rows.append(row_idx)
                        cols.append(vitals_offset + v_idx)
                        data.append(float(v_val))

        return sparse.csr_matrix(
            (data, (rows, cols)),
            shape=(num_records, num_features),
            dtype=np.float32,
        )

    def fit_transform(self, records: list[ClassificationRecord]) -> sparse.csr_matrix:
        return self.fit(records).transform(records)

    @property
    def all_feature_names(self) -> list[str]:
        if self.idx_to_feature is None:
            return []
        return (
            self.idx_to_feature
            + (self.stat_feature_names or [])
            + (self.clinical_feature_names or [])
        )
