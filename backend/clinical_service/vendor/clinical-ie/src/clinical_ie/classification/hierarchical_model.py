"""Hierarchical Two-Stage Classifier for Clinical Respiratory Disease Diagnosis."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import sparse
from sklearn.linear_model import LogisticRegression

from . import ID_TO_LABEL, LABELS, LABEL_TO_ID
from .tabular_model import evaluate_predictions, train_lightgbm

# 3 Primary Diagnostic Super-Clusters:
# Cluster 0: Normal (Binhthuong)
# Cluster 1: Acute Respiratory Diseases (Viemphoi, Covid, Suyhohap, Trandich, Trankhi, Phuphoi)
# Cluster 2: Chronic / Structural / Neoplastic (COPD, Hen, Lao, Uphoi, Xepphoi)
CLUSTER_NAMES = ("Normal", "Acute", "Chronic")

ACUTE_LABELS = ("Viemphoi", "Covid", "Suyhohap", "Trandich", "Trankhi", "Phuphoi")
CHRONIC_LABELS = ("COPD", "Hen", "Lao", "Uphoi", "Xepphoi")

LABEL_TO_CLUSTER: dict[str, int] = {"Binhthuong": 0}
for _l in ACUTE_LABELS:
    LABEL_TO_CLUSTER[_l] = 1
for _l in CHRONIC_LABELS:
    LABEL_TO_CLUSTER[_l] = 2

CLASS_ID_TO_CLUSTER: dict[int, int] = {
    LABEL_TO_ID[label]: cluster for label, cluster in LABEL_TO_CLUSTER.items()
}

ACUTE_CLASS_IDS: list[int] = sorted([LABEL_TO_ID[l] for l in ACUTE_LABELS])
CHRONIC_CLASS_IDS: list[int] = sorted([LABEL_TO_ID[l] for l in CHRONIC_LABELS])


class HierarchicalClinicalClassifier:
    """Two-stage clinical diagnostic model mirroring physician reasoning:

    Stage 1: Screen into Normal vs Acute vs Chronic respiratory syndromes.
    Stage 2: Specialist differential diagnosis within acute and chronic disease clusters.
    """

    def __init__(
        self,
        base_model_type: str = "lgbm",
        n_estimators: int = 250,
        random_state: int = 42,
    ) -> None:
        self.base_model_type = base_model_type
        self.n_estimators = n_estimators
        self.random_state = random_state

        self.root_classifier: Any = None
        self.acute_specialist: Any = None
        self.chronic_specialist: Any = None

        # Index maps for mapping specialist outputs back to global 12-class space
        self.acute_id_to_idx = {cid: idx for idx, cid in enumerate(ACUTE_CLASS_IDS)}
        self.chronic_id_to_idx = {cid: idx for idx, cid in enumerate(CHRONIC_CLASS_IDS)}

    def _train_component(
        self,
        X_train: sparse.csr_matrix,
        y_train: np.ndarray,
        num_classes: int,
    ) -> Any:
        if self.base_model_type == "lgbm":
            return train_lightgbm(
                X_train,
                y_train,
                n_estimators=self.n_estimators,
                class_weight="balanced",
                random_state=self.random_state,
            )
        return LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            random_state=self.random_state,
        ).fit(X_train, y_train)

    def fit(self, X_train: sparse.csr_matrix, y_train: np.ndarray) -> HierarchicalClinicalClassifier:
        """Fit Stage 1 root cluster model and Stage 2 cluster-specific specialists."""
        # 1. Stage 1: Root Cluster Labels
        y_clusters = np.array([CLASS_ID_TO_CLUSTER[int(y)] for y in y_train], dtype=np.int32)
        print("   - Training Stage 1 Root Cluster Classifier (3 clusters)...")
        self.root_classifier = self._train_component(X_train, y_clusters, num_classes=3)

        # 2. Stage 2: Acute Specialist
        acute_mask = y_clusters == 1
        X_train_acute = X_train[acute_mask]
        y_train_acute_global = y_train[acute_mask]
        # Re-index acute classes to local 0..5
        y_train_acute_local = np.array([self.acute_id_to_idx[y] for y in y_train_acute_global], dtype=np.int32)
        print(f"   - Training Stage 2 Acute Specialist ({len(y_train_acute_local)} samples, 6 classes)...")
        self.acute_specialist = self._train_component(
            X_train_acute, y_train_acute_local, num_classes=len(ACUTE_CLASS_IDS)
        )

        # 3. Stage 2: Chronic Specialist
        chronic_mask = y_clusters == 2
        X_train_chronic = X_train[chronic_mask]
        y_train_chronic_global = y_train[chronic_mask]
        # Re-index chronic classes to local 0..4
        y_train_chronic_local = np.array([self.chronic_id_to_idx[y] for y in y_train_chronic_global], dtype=np.int32)
        print(f"   - Training Stage 2 Chronic Specialist ({len(y_train_chronic_local)} samples, 5 classes)...")
        self.chronic_specialist = self._train_component(
            X_train_chronic, y_train_chronic_local, num_classes=len(CHRONIC_CLASS_IDS)
        )

        return self

    def predict_proba(self, X: sparse.csr_matrix) -> np.ndarray:
        """Compute unified 12-class posterior probabilities via conditional chain rule:

        P(y = c | x) = P(Cluster(c) | x) * P(y = c | Cluster(c), x)
        """
        if self.root_classifier is None:
            raise RuntimeError("HierarchicalClinicalClassifier must be fitted before predict_proba.")

        num_samples = X.shape[0]
        root_probs = self.root_classifier.predict_proba(X)  # (N, 3): [Normal, Acute, Chronic]
        acute_probs = self.acute_specialist.predict_proba(X)  # (N, 6)
        chronic_probs = self.chronic_specialist.predict_proba(X)  # (N, 5)

        full_probs = np.zeros((num_samples, len(LABELS)), dtype=np.float32)

        # Class 0: Normal
        normal_id = LABEL_TO_ID["Binhthuong"]
        full_probs[:, normal_id] = root_probs[:, 0]

        # Acute classes (1): P(Acute) * P(class | Acute)
        p_acute = root_probs[:, 1, np.newaxis]
        for global_id in ACUTE_CLASS_IDS:
            local_idx = self.acute_id_to_idx[global_id]
            full_probs[:, global_id] = (p_acute * acute_probs[:, local_idx, np.newaxis]).squeeze(-1)

        # Chronic classes (2): P(Chronic) * P(class | Chronic)
        p_chronic = root_probs[:, 2, np.newaxis]
        for global_id in CHRONIC_CLASS_IDS:
            local_idx = self.chronic_id_to_idx[global_id]
            full_probs[:, global_id] = (p_chronic * chronic_probs[:, local_idx, np.newaxis]).squeeze(-1)

        # Normalize rows to guarantee sum = 1.0
        row_sums = full_probs.sum(axis=-1, keepdims=True)
        row_sums = np.where(row_sums == 0, 1.0, row_sums)
        return full_probs / row_sums

    def predict(self, X: sparse.csr_matrix) -> np.ndarray:
        probs = self.predict_proba(X)
        return np.argmax(probs, axis=-1)

    def evaluate(self, X: sparse.csr_matrix, y: np.ndarray, split_name: str = "validation") -> dict[str, Any]:
        probs = self.predict_proba(X)
        preds = np.argmax(probs, axis=-1)
        return evaluate_predictions(y, preds, probs, split_name=split_name)
