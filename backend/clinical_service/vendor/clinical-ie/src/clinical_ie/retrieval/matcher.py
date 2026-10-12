"""Graph-based case similarity matcher and explainable subgraph alignment."""
from __future__ import annotations

from typing import Any

from .clinical_context import extract_retrieval_vitals, graph_elements, text_concepts, vitals_similarity
from .index import ClinicalGraphIndex
from .schema import SimilarCase


def _extract_graph_elements(graph: dict[str, Any]) -> tuple[set[str], set[str]]:
    return graph_elements(graph)


class CaseSimilarityMatcher:
    """Computes clinical graph similarity and extracts overlapping subgraphs for Case-Based Reasoning."""

    def __init__(
        self,
        graph_index: ClinicalGraphIndex,
        weight_graph: float = 0.65,
        weight_vitals: float = 0.35,
    ) -> None:
        self.index = graph_index
        self.weight_graph = weight_graph
        self.weight_vitals = weight_vitals

        # Pre-extract elements for all corpus cases to enable fast matching
        self.cached_elements: dict[str, tuple[set[str], set[str]]] = {}
        for did, rec in self.index.records.items():
            self.cached_elements[did] = _extract_graph_elements(rec.graph or {})

    def find_similar(
        self,
        query_graph: dict[str, Any] | None = None,
        query_text: str | None = None,
        candidate_doc_ids: set[str] | list[str] | None = None,
        top_k: int = 5,
        min_similarity: float = 0.05,
    ) -> list[SimilarCase]:
        """Find the most similar patient cases in the corpus given a query case."""
        q_concepts, q_triples = _extract_graph_elements(query_graph or {})
        if top_k <= 0:
            return []
        if not 0.0 <= min_similarity <= 1.0:
            raise ValueError("min_similarity must be between 0 and 1")
        q_vitals = extract_retrieval_vitals(query_text or "", query_graph)

        # Narrow down candidates if not specified: filter candidates having at least 1 overlapping concept
        candidates: set[str]
        if candidate_doc_ids is not None:
            candidates = set(candidate_doc_ids)
        else:
            candidates = set()
            for c in q_concepts:
                parts = c.split(":", 1)
                if len(parts) == 2:
                    candidates.update(self.index.search_concept(parts[0], parts[1], temporality="current"))
            has_entities = any(n.get("kind") == "Entity" for n in (query_graph or {}).get("nodes", []))
            if not candidates and query_text and not has_entities:
                vocabulary = {c for cs, _ in self.cached_elements.values() for c in cs}
                q_concepts = text_concepts(query_text, vocabulary)
                for concept in q_concepts:
                    etype, name = concept.split(":", 1)
                    candidates.update(self.index.search_concept(etype, name, temporality="current"))

        scored_cases: list[SimilarCase] = []

        for did in candidates:
            rec = self.index.records.get(did)
            if not rec:
                continue

            t_concepts, t_triples = self.cached_elements.get(did, (set(), set()))
            t_vitals = self.index.doc_vitals_features.get(did, {})

            # 1. Graph Overlap
            overlap_c = q_concepts.intersection(t_concepts)
            overlap_t = q_triples.intersection(t_triples)

            union_c = q_concepts.union(t_concepts)
            union_t = q_triples.union(t_triples)

            jaccard_c = len(overlap_c) / len(union_c) if union_c else 0.0
            jaccard_t = len(overlap_t) / len(union_t) if union_t else 0.0
            graph_sim = 0.75 * jaccard_c + 0.25 * jaccard_t

            vitals_sim = vitals_similarity(q_vitals, t_vitals)

            # Composite Score
            total_sim = self.weight_graph * graph_sim + self.weight_vitals * vitals_sim

            if overlap_c and total_sim >= min_similarity:
                scored_cases.append(
                    SimilarCase(
                        doc_id=did,
                        label=rec.label,
                        similarity_score=round(float(total_sim), 4),
                        graph_similarity=round(float(graph_sim), 4),
                        semantic_similarity=round(float(graph_sim), 4),
                        vitals_similarity=round(float(vitals_sim), 4),
                        overlapping_concepts=sorted(list(overlap_c)),
                        overlapping_triples=sorted(list(overlap_t)),
                        text_snippet=rec.text[:180] + "..." if rec.text else "",
                        full_graph=rec.graph,
                    )
                )

        scored_cases.sort(key=lambda c: (-c.similarity_score, c.doc_id))
        return scored_cases[:top_k]
