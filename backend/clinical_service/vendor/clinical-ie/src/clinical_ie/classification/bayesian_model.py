"""Probabilistic Graphical and Bayesian models for 12-class clinical differential diagnosis."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import sparse
from sklearn.naive_bayes import ComplementNB, MultinomialNB

from . import ID_TO_LABEL, LABELS, LABEL_TO_ID
from .tabular_model import evaluate_predictions


@dataclass
class ClinicalBayesianClassifier:
    """Probabilistic Bayesian classifier with prior temperature softening and class threshold tuning."""

    model_type: str = "multinomial"  # "multinomial" or "complement"
    alpha: float = 1.0
    prior_temperature: float = 0.25  # 1.0 = standard prior, 0.0 = uniform prior, 0.25 = evidence-focused
    class_biases: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.model_type == "multinomial":
            self.model = MultinomialNB(alpha=self.alpha)
        elif self.model_type == "complement":
            self.model = ComplementNB(alpha=self.alpha, norm=True)
        else:
            raise ValueError(f"Unknown Bayesian model type: {self.model_type}")

    def fit(self, X: sparse.csr_matrix, y: np.ndarray) -> ClinicalBayesianClassifier:
        self.model.fit(X, y)
        if self.prior_temperature != 1.0:
            natural_prior = np.log(np.bincount(y, minlength=len(LABELS)) / len(y))
            if self.prior_temperature == 0.0:
                softened = np.full(len(LABELS), -np.log(len(LABELS)))
            else:
                unnorm = self.prior_temperature * natural_prior
                softened = unnorm - np.log(np.sum(np.exp(unnorm)))
            self.model.class_log_prior_ = softened
        return self

    def tune_class_biases(self, X_val: sparse.csr_matrix, y_val: np.ndarray, iterations: int = 5) -> np.ndarray:
        """Optimize additive class log-prior biases on validation set to maximize Macro-F1."""
        val_log_probs = self.model.predict_log_proba(X_val)
        num_classes = len(LABELS)
        biases = np.zeros(num_classes)

        current_preds = np.argmax(val_log_probs, axis=-1)
        best_f1 = evaluate_predictions(y_val, current_preds)["macro_f1"]

        search_deltas = [-1.5, -1.0, -0.5, -0.2, 0.2, 0.5, 1.0, 1.5, 2.0, 3.0]

        for _ in range(iterations):
            for c in range(num_classes):
                best_delta = 0.0
                for delta in search_deltas:
                    trial = biases.copy()
                    trial[c] += delta
                    preds = np.argmax(val_log_probs + trial, axis=-1)
                    score = evaluate_predictions(y_val, preds)["macro_f1"]
                    if score > best_f1:
                        best_f1 = score
                        best_delta = delta
                biases[c] += best_delta

        self.class_biases = biases
        return biases

    def predict_log_proba(self, X: sparse.csr_matrix) -> np.ndarray:
        log_probs = self.model.predict_log_proba(X)
        if self.class_biases is not None:
            log_probs = log_probs + self.class_biases
        return log_probs

    def predict_proba(self, X: sparse.csr_matrix) -> np.ndarray:
        log_probs = self.predict_log_proba(X)
        # Numerically stable softmax
        max_lp = np.max(log_probs, axis=-1, keepdims=True)
        exp_lp = np.exp(log_probs - max_lp)
        return exp_lp / np.sum(exp_lp, axis=-1, keepdims=True)

    def predict(self, X: sparse.csr_matrix) -> np.ndarray:
        log_probs = self.predict_log_proba(X)
        return np.argmax(log_probs, axis=-1)

    def evaluate(self, X: sparse.csr_matrix, y: np.ndarray, split_name: str = "validation") -> dict[str, Any]:
        preds = self.predict(X)
        probs = self.predict_proba(X)
        return evaluate_predictions(y, preds, probs, split_name=split_name)
