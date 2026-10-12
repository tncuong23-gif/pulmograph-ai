"""Disease classification module from clinical graphs and prediagnosis text."""
from __future__ import annotations

LABELS = (
    "Binhthuong",
    "COPD",
    "Covid",
    "Hen",
    "Lao",
    "Phuphoi",
    "Suyhohap",
    "Trandich",
    "Trankhi",
    "Uphoi",
    "Viemphoi",
    "Xepphoi",
)

LABEL_TO_ID = {label: idx for idx, label in enumerate(LABELS)}
ID_TO_LABEL = {idx: label for idx, label in enumerate(LABELS)}

from .hybrid import HybridClassifier, HybridPrediction, TopClass
