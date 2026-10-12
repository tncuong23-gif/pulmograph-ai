"""Relational Graph Attention Network (RGAT) with dense semantic embeddings for clinical classification."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from torch_geometric.data import Data
from torch_geometric.nn import GATv2Conv, global_mean_pool

from . import LABELS, LABEL_TO_ID
from .dataset import ClassificationRecord
from .tabular_model import evaluate_predictions

PREDICATES = (
    "HAS_SYMPTOM",
    "HAS_SIGN",
    "HAS_CONDITION",
    "HAS_HISTORY",
    "HAS_TEST",
    "HAS_TREATMENT",
    "HAS_RESULT",
    "REVEALS",
    "LOCATED_AT",
    "TREATED_WITH",
    "HAS_DURATION",
    "ONSET_AT",
    "HAS_FREQUENCY",
    "OCCURS_AT",
    "NOT_IMPROVED_BY",
    "SELF_LOOP",
)
PREDICATE_TO_ID = {p: i for i, p in enumerate(PREDICATES)}

ENTITY_TYPES = (
    "CASE",
    "SYMPTOM",
    "SIGN",
    "CONDITION",
    "TEST",
    "RESULT",
    "ANATOMY",
    "TREATMENT",
    "TIME",
    "UNKNOWN",
)
ENTITY_TYPE_TO_ID = {t: i for i, t in enumerate(ENTITY_TYPES)}

ASSERTIONS = ("PRESENT", "NEGATED", "POSSIBLE", "UNKNOWN")
ASSERTION_TO_ID = {a: i for i, a in enumerate(ASSERTIONS)}

TEMPORALITIES = ("CURRENT", "HISTORY", "FUTURE", "UNKNOWN")
TEMPORALITY_TO_ID = {t: i for i, t in enumerate(TEMPORALITIES)}


def _normalize(text: str) -> str:
    cleaned = unicodedata.normalize("NFC", text).strip().casefold()
    return re.sub(r"\s+", " ", cleaned)


class DenseSemanticEncoder:
    """Encodes clinical entity phrases into a continuous 64-dimensional semantic space."""

    def __init__(self, n_components: int = 64) -> None:
        self.n_components = n_components
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
        self.svd = TruncatedSVD(n_components=n_components, random_state=42)
        self.cache: dict[str, np.ndarray] = {}

    def fit(self, records: list[ClassificationRecord]) -> DenseSemanticEncoder:
        phrases: set[str] = set()
        for rec in records:
            for node in rec.graph.get("nodes", []):
                if node.get("kind") == "Entity":
                    raw = str(node.get("properties", {}).get("text", ""))
                    norm = _normalize(raw)
                    if norm:
                        phrases.add(norm)

        phrases_list = sorted(phrases)
        if len(phrases_list) < self.n_components:
            self.n_components = max(len(phrases_list) - 1, 2)
            self.svd = TruncatedSVD(n_components=self.n_components, random_state=42)

        X_tfidf = self.vectorizer.fit_transform(phrases_list)
        X_svd = self.svd.fit_transform(X_tfidf).astype(np.float32)

        for phrase, vec in zip(phrases_list, X_svd):
            self.cache[phrase] = vec

        return self

    def encode(self, text: str) -> np.ndarray:
        norm = _normalize(text)
        if not norm:
            return np.zeros(self.n_components, dtype=np.float32)
        cached = self.cache.get(norm)
        if cached is not None:
            return cached
        # Fallback for unseen test words
        X_tf = self.vectorizer.transform([norm])
        vec = self.svd.transform(X_tf)[0].astype(np.float32)
        self.cache[norm] = vec
        return vec


def graph_to_pyg_data(
    record: ClassificationRecord,
    semantic_encoder: DenseSemanticEncoder,
) -> Data:
    """Convert a clinical graph into a PyG Data object with dense semantic node features."""
    nodes = record.graph.get("nodes", [])
    edges = record.graph.get("edges", [])

    node_uid_to_idx: dict[str, int] = {}
    type_ids: list[int] = []
    assert_ids: list[int] = []
    temp_ids: list[int] = []
    semantic_vecs: list[np.ndarray] = []
    confidences: list[float] = []
    is_case_flags: list[float] = []

    case_idx = 0
    for idx, node in enumerate(nodes):
        uid = node.get("uid", "")
        node_uid_to_idx[uid] = idx
        kind = node.get("kind", "Entity")
        props = node.get("properties", {})

        if kind == "Case":
            case_idx = idx
            etype = "CASE"
            assertion = "UNKNOWN"
            temporality = "UNKNOWN"
            conf = 1.0
            s_vec = np.zeros(semantic_encoder.n_components, dtype=np.float32)
            is_case = 1.0
        else:
            etype = str(props.get("entity_type", "UNKNOWN")).upper()
            assertion = str(props.get("assertion", "PRESENT")).upper()
            temporality = str(props.get("temporality", "CURRENT")).upper()
            conf = float(props.get("confidence", 1.0))
            raw_text = str(props.get("text", ""))
            s_vec = semantic_encoder.encode(raw_text)
            is_case = 0.0

        type_ids.append(ENTITY_TYPE_TO_ID.get(etype, ENTITY_TYPE_TO_ID["UNKNOWN"]))
        assert_ids.append(ASSERTION_TO_ID.get(assertion, ASSERTION_TO_ID["UNKNOWN"]))
        temp_ids.append(TEMPORALITY_TO_ID.get(temporality, TEMPORALITY_TO_ID["UNKNOWN"]))
        semantic_vecs.append(s_vec)
        confidences.append(conf)
        is_case_flags.append(is_case)

    # Edge indices & one-hot predicates
    edge_src: list[int] = []
    edge_dst: list[int] = []
    edge_type_ids: list[int] = []

    for edge in edges:
        s_uid = edge.get("source")
        t_uid = edge.get("target")
        if s_uid in node_uid_to_idx and t_uid in node_uid_to_idx:
            pred = str(edge.get("predicate", "UNKNOWN")).upper()
            ptype = PREDICATE_TO_ID.get(pred, PREDICATE_TO_ID["SELF_LOOP"])
            s_idx = node_uid_to_idx[s_uid]
            t_idx = node_uid_to_idx[t_uid]

            edge_src.append(s_idx)
            edge_dst.append(t_idx)
            edge_type_ids.append(ptype)

            # Bidirectional flow to allow information to flow back to Case
            edge_src.append(t_idx)
            edge_dst.append(s_idx)
            edge_type_ids.append(ptype)

    # Self loops for all nodes
    for idx in range(len(nodes)):
        edge_src.append(idx)
        edge_dst.append(idx)
        edge_type_ids.append(PREDICATE_TO_ID["SELF_LOOP"])

    edge_index = torch.tensor([edge_src, edge_dst], dtype=torch.long)
    edge_type_tensor = torch.tensor(edge_type_ids, dtype=torch.long)
    edge_attr = F.one_hot(edge_type_tensor, num_classes=len(PREDICATES)).float()

    sem_tensor = torch.tensor(np.array(semantic_vecs, dtype=np.float32))

    data = Data(
        edge_index=edge_index,
        edge_attr=edge_attr,
        type_ids=torch.tensor(type_ids, dtype=torch.long),
        assert_ids=torch.tensor(assert_ids, dtype=torch.long),
        temp_ids=torch.tensor(temp_ids, dtype=torch.long),
        semantic_vecs=sem_tensor,
        confidences=torch.tensor(confidences, dtype=torch.float).unsqueeze(1),
        is_case=torch.tensor(is_case_flags, dtype=torch.float).unsqueeze(1),
        y=torch.tensor([record.class_id], dtype=torch.long),
        doc_id=record.doc_id,
        num_nodes=len(nodes),
    )
    return data


class ClinicalRGAT(nn.Module):
    """Relational Graph Attention Network with Case-centric pooling and semantic node initialization."""

    def __init__(
        self,
        semantic_dim: int = 64,
        hidden_dim: int = 128,
        num_classes: int = len(LABELS),
        num_predicates: int = len(PREDICATES),
        heads: int = 2,
        dropout: float = 0.25,
    ) -> None:
        super().__init__()
        self.type_emb = nn.Embedding(len(ENTITY_TYPES), 16)
        self.assert_emb = nn.Embedding(len(ASSERTIONS), 8)
        self.temp_emb = nn.Embedding(len(TEMPORALITIES), 8)

        in_dim = 16 + 8 + 8 + semantic_dim + 1 + 1  # 16+8+8+64+1+1 = 98
        self.node_proj = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
        )

        self.gat1 = GATv2Conv(hidden_dim, hidden_dim, edge_dim=num_predicates, heads=heads, concat=False)
        self.ln1 = nn.LayerNorm(hidden_dim)

        self.gat2 = GATv2Conv(hidden_dim, hidden_dim, edge_dim=num_predicates, heads=heads, concat=False)
        self.ln2 = nn.LayerNorm(hidden_dim)

        self.classifier = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, num_classes),
        )

    def forward(self, data: Data) -> torch.Tensor:
        t_emb = self.type_emb(data.type_ids)
        a_emb = self.assert_emb(data.assert_ids)
        tmp_emb = self.temp_emb(data.temp_ids)

        x_raw = torch.cat([t_emb, a_emb, tmp_emb, data.semantic_vecs, data.confidences, data.is_case], dim=-1)
        x = self.node_proj(x_raw)

        # Message Passing Layer 1
        h1 = self.gat1(x, data.edge_index, edge_attr=data.edge_attr)
        h1 = self.ln1(h1 + x)
        h1 = F.gelu(h1)

        # Message Passing Layer 2
        h2 = self.gat2(h1, data.edge_index, edge_attr=data.edge_attr)
        h2 = self.ln2(h2 + h1)
        h2 = F.gelu(h2)

        batch = data.batch if hasattr(data, "batch") and data.batch is not None else torch.zeros(
            data.num_nodes, dtype=torch.long, device=x.device
        )

        # Global mean representation
        h_mean = global_mean_pool(h2, batch)

        # Case node representation
        case_mask = (data.is_case.squeeze(-1) > 0.5)
        if case_mask.any():
            case_nodes = h2[case_mask]
            # When batched, each graph has exactly one Case node
            h_case = case_nodes
        else:
            h_case = h_mean

        graph_repr = torch.cat([h_case, h_mean], dim=-1)
        logits = self.classifier(graph_repr)
        return logits


class FocalLoss(nn.Module):
    """Class-Balanced Focal Loss to prioritize hard samples and rare diseases."""

    def __init__(self, weight: torch.Tensor, gamma: float = 1.5) -> None:
        super().__init__()
        self.weight = weight
        self.gamma = gamma

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        ce_loss = F.cross_entropy(logits, targets, reduction="none", weight=self.weight)
        pt = torch.exp(-ce_loss)
        focal_loss = ((1.0 - pt) ** self.gamma) * ce_loss
        return focal_loss.mean()
