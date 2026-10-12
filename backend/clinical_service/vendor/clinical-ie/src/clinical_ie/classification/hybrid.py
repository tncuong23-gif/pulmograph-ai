"""Hybrid Multimodal Classifier v1 (Text TF-IDF + Graph GBDT + Naive Bayes with Calibrated Biases).

This module implements the production inference bundle and save/load logic for the
12-class respiratory disease classifier.

Scores produced are model decision scores for ranking, NOT clinical diagnostic probabilities.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from . import ID_TO_LABEL, LABELS, LABEL_TO_ID
from .bayesian_model import ClinicalBayesianClassifier
from .dataset import ClassificationRecord
from .feature_extractor import GraphFeatureExtractor

DISCLAIMER_TEXT = (
    "Điểm số là giá trị quyết định của mô hình (decision scores) phục vụ xếp hạng nghiên cứu, "
    "không phải xác suất chẩn đoán và không dùng cho ca bệnh thực tế."
)


@dataclass(frozen=True)
class TopClass:
    rank: int
    label: str
    calibrated_score: float
    raw_probability: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "label": self.label,
            "calibrated_score": round(self.calibrated_score, 4),
            "raw_probability": round(self.raw_probability, 4),
        }


@dataclass(frozen=True)
class HybridPrediction:
    top5: list[TopClass]
    all_scores: dict[str, float]
    all_probabilities: dict[str, float]
    branch_probabilities: dict[str, dict[str, float]]
    is_empty_graph: bool
    is_empty_text: bool
    status: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "top5": [c.to_dict() for c in self.top5],
            "all_scores": {k: round(v, 4) for k, v in self.all_scores.items()},
            "all_probabilities": {k: round(v, 4) for k, v in self.all_probabilities.items()},
            "branch_probabilities": {
                b: {k: round(v, 4) for k, v in p.items()}
                for b, p in self.branch_probabilities.items()
            },
            "is_empty_graph": self.is_empty_graph,
            "is_empty_text": self.is_empty_text,
            "status": self.status,
            "warnings": self.warnings,
        }


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class HybridClassifier:
    """Production hybrid classifier combining text, graph structure, and clinical bayesian priors."""

    def __init__(
        self,
        text_vectorizer: Any,
        text_clf: Any,
        graph_extractor: GraphFeatureExtractor,
        graph_clf: Any,
        bayes_clf: ClinicalBayesianClassifier,
        *,
        labels: tuple[str, ...] = LABELS,
        fusion_weights: dict[str, float] | None = None,
        calibrated_biases: np.ndarray | list[float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.text_vectorizer = text_vectorizer
        self.text_clf = text_clf
        self.graph_extractor = graph_extractor
        self.graph_clf = graph_clf
        self.bayes_clf = bayes_clf
        self.labels = tuple(labels)
        self.num_classes = len(self.labels)

        if self.labels != LABELS:
            raise ValueError(f"Label order mismatch. Expected {LABELS}, got {self.labels}")

        self.fusion_weights = fusion_weights or {"text": 0.45, "graph": 0.40, "bayes": 0.15}
        if calibrated_biases is not None:
            self.calibrated_biases = np.array(calibrated_biases, dtype=np.float64)
        else:
            self.calibrated_biases = np.zeros(self.num_classes, dtype=np.float64)

        if len(self.calibrated_biases) != self.num_classes:
            raise ValueError(
                f"Calibrated biases length ({len(self.calibrated_biases)}) "
                f"must match number of classes ({self.num_classes})"
            )

        self.metadata = metadata or {}

    def predict(
        self,
        text: str | None = None,
        graph: dict[str, Any] | None = None,
    ) -> HybridPrediction:
        """Predict top classes from prediagnosis text and/or extracted case graph.

        Handles missing text, empty graphs, and isolated entities cleanly.
        """
        clean_text = (text or "").strip()
        is_empty_text = len(clean_text) == 0

        num_nodes = len(graph.get("nodes", [])) if (graph and isinstance(graph, dict)) else 0
        is_empty_graph = num_nodes <= 1

        warnings = [DISCLAIMER_TEXT]
        status = "normal"

        if is_empty_text and is_empty_graph:
            warnings.append("Cả văn bản và đồ thị đều thiếu dữ liệu; trả phân bố đều mặc định.")
            uniform_prob = 1.0 / self.num_classes
            scores = {lab: 0.0 for lab in self.labels}
            probs = {lab: uniform_prob for lab in self.labels}
            top5 = [
                TopClass(rank=i + 1, label=lab, calibrated_score=0.0, raw_probability=uniform_prob)
                for i, lab in enumerate(self.labels[:5])
            ]
            return HybridPrediction(
                top5=top5,
                all_scores=scores,
                all_probabilities=probs,
                branch_probabilities={"text": probs, "graph": probs, "bayes": probs},
                is_empty_graph=True,
                is_empty_text=True,
                status="insufficient_information",
                warnings=warnings,
            )

        # 1. Text branch prediction
        if not is_empty_text:
            X_text = self.text_vectorizer.transform([clean_text])
            text_probs = self.text_clf.predict_proba(X_text)[0]
        else:
            text_probs = np.full(self.num_classes, 1.0 / self.num_classes, dtype=np.float64)
            warnings.append("Thiếu văn bản; chỉ sử dụng thông tin từ đồ thị ca bệnh.")

        # 2. Graph & Bayes branch predictions
        if not is_empty_graph and graph is not None:
            mock_rec = ClassificationRecord(
                doc_id=str(graph.get("doc_id", "query_case")),
                label="Binhthuong",
                class_id=0,
                graph=graph,
                text=clean_text,
            )
            X_graph = self.graph_extractor.transform([mock_rec])
            if hasattr(self.graph_clf, "predict_proba"):
                graph_probs = self.graph_clf.predict_proba(X_graph)[0]
            else:
                raw_pred = self.graph_clf.predict(X_graph)
                graph_probs = raw_pred[0] if getattr(raw_pred, "ndim", 1) == 2 else raw_pred

            if hasattr(self.bayes_clf, "model") and hasattr(self.bayes_clf.model, "predict_proba"):
                bayes_probs = self.bayes_clf.model.predict_proba(X_graph)[0]
            elif hasattr(self.bayes_clf, "predict_proba"):
                bayes_probs = self.bayes_clf.predict_proba(X_graph)[0]
            else:
                bayes_probs = np.full(self.num_classes, 1.0 / self.num_classes, dtype=np.float64)
        else:
            graph_probs = np.full(self.num_classes, 1.0 / self.num_classes, dtype=np.float64)
            bayes_probs = np.full(self.num_classes, 1.0 / self.num_classes, dtype=np.float64)
            if is_empty_graph:
                warnings.append("Đồ thị ca bệnh rỗng; chuyển hoàn toàn sang nhánh phân lớp văn bản.")

        # 3. Gated Fusion
        if is_empty_graph:
            w_text = 1.0
            w_graph = 0.0
            w_bayes = 0.0
            status = "fallback_text_only"
        elif is_empty_text:
            w_text = 0.0
            sum_gb = self.fusion_weights.get("graph", 0.40) + self.fusion_weights.get("bayes", 0.15)
            w_graph = self.fusion_weights.get("graph", 0.40) / sum_gb if sum_gb > 0 else 0.7
            w_bayes = self.fusion_weights.get("bayes", 0.15) / sum_gb if sum_gb > 0 else 0.3
            status = "fallback_graph_only"
        else:
            w_text = self.fusion_weights.get("text", 0.45)
            w_graph = self.fusion_weights.get("graph", 0.40)
            w_bayes = self.fusion_weights.get("bayes", 0.15)

        raw_fused_probs = w_text * text_probs + w_graph * graph_probs + w_bayes * bayes_probs

        # Normalize raw fused probs
        prob_sum = float(np.sum(raw_fused_probs))
        if prob_sum > 0:
            raw_fused_probs = raw_fused_probs / prob_sum
        else:
            raw_fused_probs = np.full(self.num_classes, 1.0 / self.num_classes)

        # 4. Calibrated Decision Score
        # scores = log(p + 1e-9) + calibrated_biases
        log_probs = np.log(raw_fused_probs + 1e-9)
        calibrated_scores = log_probs + self.calibrated_biases

        ranked_indices = np.argsort(-calibrated_scores)

        top5 = [
            TopClass(
                rank=i + 1,
                label=self.labels[idx],
                calibrated_score=float(calibrated_scores[idx]),
                raw_probability=float(raw_fused_probs[idx]),
            )
            for i, idx in enumerate(ranked_indices[:5])
        ]

        all_scores = {self.labels[i]: float(calibrated_scores[i]) for i in range(self.num_classes)}
        all_probs = {self.labels[i]: float(raw_fused_probs[i]) for i in range(self.num_classes)}

        branch_probs = {
            "text": {self.labels[i]: float(text_probs[i]) for i in range(self.num_classes)},
            "graph": {self.labels[i]: float(graph_probs[i]) for i in range(self.num_classes)},
            "bayes": {self.labels[i]: float(bayes_probs[i]) for i in range(self.num_classes)},
        }

        return HybridPrediction(
            top5=top5,
            all_scores=all_scores,
            all_probabilities=all_probs,
            branch_probabilities=branch_probs,
            is_empty_graph=is_empty_graph,
            is_empty_text=is_empty_text,
            status=status,
            warnings=warnings,
        )

    def save_bundle(self, bundle_dir: Path | str) -> dict[str, Any]:
        """Serialize all three branches, feature extractors, fusion weights, and SHA-256 manifest."""
        out = Path(bundle_dir)
        out.mkdir(parents=True, exist_ok=True)

        text_file = out / "text_branch.joblib"
        graph_file = out / "graph_branch.joblib"
        bayes_file = out / "bayes_branch.joblib"

        # Safely serialize graph classifier (LightGBM Booster is serialized to string to avoid C++ segfaults)
        if hasattr(self.graph_clf, "booster_"):
            graph_payload = {
                "is_lgb_booster": True,
                "model_str": self.graph_clf.booster_.model_to_string(),
            }
        elif hasattr(self.graph_clf, "model_to_string"):
            graph_payload = {
                "is_lgb_booster": True,
                "model_str": self.graph_clf.model_to_string(),
            }
        else:
            graph_payload = {
                "is_lgb_booster": False,
                "model": self.graph_clf,
            }

        joblib.dump({"vectorizer": self.text_vectorizer, "model": self.text_clf}, text_file, compress=3)
        joblib.dump({"extractor": self.graph_extractor, "model_payload": graph_payload}, graph_file, compress=3)
        joblib.dump({"model": self.bayes_clf}, bayes_file, compress=3)

        manifest = {
            "schema_version": "1.0",
            "bundle_name": "classifier-bundle-v1",
            "labels": list(self.labels),
            "fusion_weights": self.fusion_weights,
            "calibrated_biases": self.calibrated_biases.tolist(),
            "files": {
                "text_branch.joblib": _sha256_file(text_file),
                "graph_branch.joblib": _sha256_file(graph_file),
                "bayes_branch.joblib": _sha256_file(bayes_file),
            },
            "metadata": self.metadata,
        }

        with (out / "bundle.json").open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)

        return manifest

    @classmethod
    def from_bundle(cls, bundle_dir: Path | str) -> HybridClassifier:
        """Load and verify a complete 3-branch hybrid classifier bundle."""
        b_dir = Path(bundle_dir)
        manifest_path = b_dir / "bundle.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Missing classifier bundle manifest: {manifest_path}")

        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)

        labels = tuple(manifest.get("labels", []))
        if labels != LABELS:
            raise ValueError(f"Classifier bundle labels mismatch: {labels} != {LABELS}")

        # Verify checksums
        file_hashes = manifest.get("files", {})
        for filename, expected_hash in file_hashes.items():
            target_path = b_dir / filename
            if not target_path.is_file():
                raise FileNotFoundError(f"Missing required bundle file: {target_path}")
            actual_hash = _sha256_file(target_path)
            if actual_hash != expected_hash:
                raise ValueError(
                    f"Checksum mismatch for {filename} in {b_dir}: "
                    f"expected {expected_hash}, got {actual_hash}"
                )

        text_data = joblib.load(b_dir / "text_branch.joblib")
        graph_data = joblib.load(b_dir / "graph_branch.joblib")
        bayes_data = joblib.load(b_dir / "bayes_branch.joblib")

        graph_extractor = graph_data["extractor"]
        if "model_payload" in graph_data:
            payload = graph_data["model_payload"]
            if payload.get("is_lgb_booster"):
                import lightgbm as lgb
                graph_clf = lgb.Booster(model_str=payload["model_str"])
            else:
                graph_clf = payload["model"]
        else:
            graph_clf = graph_data["model"]

        return cls(
            text_vectorizer=text_data["vectorizer"],
            text_clf=text_data["model"],
            graph_extractor=graph_extractor,
            graph_clf=graph_clf,
            bayes_clf=bayes_data["model"],
            labels=labels,
            fusion_weights=manifest.get("fusion_weights"),
            calibrated_biases=manifest.get("calibrated_biases"),
            metadata=manifest.get("metadata", {}),
        )
