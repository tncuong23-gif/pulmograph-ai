"""Tabular model wrapper for LightGBM and baseline linear models with class weighting."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import sparse
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

from . import ID_TO_LABEL, LABELS, LABEL_TO_ID


def evaluate_predictions(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: np.ndarray | None = None,
    *,
    split_name: str = "validation",
) -> dict[str, Any]:
    """Calculate comprehensive classification metrics across 12 classes."""
    classes = list(range(len(LABELS)))
    macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    weighted_f1 = float(f1_score(y_true, y_pred, average="weighted", zero_division=0))
    micro_f1 = float(f1_score(y_true, y_pred, average="micro", zero_division=0))
    balanced_acc = float(balanced_accuracy_score(y_true, y_pred))
    overall_acc = float(accuracy_score(y_true, y_pred))

    prec, rec, f1s, sup = precision_recall_fscore_support(
        y_true, y_pred, labels=classes, zero_division=0
    )

    per_class: dict[str, dict[str, float]] = {}
    for idx, label in enumerate(LABELS):
        per_class[label] = {
            "precision": round(float(prec[idx]), 4),
            "recall": round(float(rec[idx]), 4),
            "f1": round(float(f1s[idx]), 4),
            "support": int(sup[idx]),
        }

    rare_labels = ("Xepphoi", "Trankhi", "Uphoi", "Phuphoi", "Hen")
    rare_f1s = [per_class[label]["f1"] for label in rare_labels if label in per_class]
    rare_macro_f1 = float(np.mean(rare_f1s)) if rare_f1s else 0.0

    cm = confusion_matrix(y_true, y_pred, labels=classes).tolist()

    return {
        "split": split_name,
        "records": int(len(y_true)),
        "macro_f1": round(macro_f1, 4),
        "balanced_accuracy": round(balanced_acc, 4),
        "weighted_f1": round(weighted_f1, 4),
        "overall_accuracy": round(overall_acc, 4),
        "rare_classes_macro_f1": round(rare_macro_f1, 4),
        "per_class": per_class,
        "confusion_matrix": cm,
        "labels": list(LABELS),
    }


def tune_threshold_biases(
    y_true: np.ndarray,
    scores: np.ndarray,
    iterations: int = 5,
    search_deltas: tuple[float, ...] = (-1.5, -1.0, -0.5, -0.2, -0.1, 0.1, 0.2, 0.5, 1.0, 1.5, 2.0, 3.0),
) -> np.ndarray:
    """Optimize per-class additive decision biases on validation set to maximize Macro-F1."""
    num_classes = scores.shape[1]
    biases = np.zeros(num_classes, dtype=np.float64)
    best_preds = np.argmax(scores, axis=-1)
    best_f1 = float(f1_score(y_true, best_preds, average="macro", zero_division=0))

    for _ in range(iterations):
        for c in range(num_classes):
            best_delta = 0.0
            for delta in search_deltas:
                trial = biases.copy()
                trial[c] += delta
                trial_preds = np.argmax(scores + trial, axis=-1)
                score = float(f1_score(y_true, trial_preds, average="macro", zero_division=0))
                if score > best_f1:
                    best_f1 = score
                    best_delta = delta
            biases[c] += best_delta

    return biases


def train_lightgbm(
    X_train: sparse.csr_matrix,
    y_train: np.ndarray,
    X_val: sparse.csr_matrix | None = None,
    y_val: np.ndarray | None = None,
    *,
    n_estimators: int = 300,
    learning_rate: float = 0.05,
    num_leaves: int = 31,
    max_depth: int = 6,
    class_weight: str = "balanced",
    random_state: int = 42,
) -> Any:
    """Train a LightGBM multi-class model with balanced class weighting."""
    try:
        import lightgbm as lgb
    except ImportError as err:
        raise RuntimeError("lightgbm is not installed. Install with: pip install lightgbm") from err

    model = lgb.LGBMClassifier(
        objective="multiclass",
        num_class=len(LABELS),
        n_estimators=n_estimators,
        learning_rate=learning_rate,
        num_leaves=num_leaves,
        max_depth=max_depth,
        class_weight=class_weight,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=random_state,
        n_jobs=-1,
        verbosity=-1,
    )

    fit_kwargs: dict[str, Any] = {}
    if X_val is not None and y_val is not None:
        fit_kwargs["eval_set"] = [(X_val, y_val)]
        fit_kwargs["callbacks"] = [lgb.early_stopping(stopping_rounds=30, verbose=False)]

    model.fit(X_train, y_train, **fit_kwargs)
    return model


def train_logistic_regression(
    X_train: sparse.csr_matrix,
    y_train: np.ndarray,
    *,
    C: float = 1.0,
    class_weight: str = "balanced",
    random_state: int = 42,
) -> Any:
    """Train a multi-class Logistic Regression model as a fast linear baseline."""
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(
        C=C,
        class_weight=class_weight,
        max_iter=1000,
        random_state=random_state,
        solver="lbfgs",
    )
    model.fit(X_train, y_train)
    return model
