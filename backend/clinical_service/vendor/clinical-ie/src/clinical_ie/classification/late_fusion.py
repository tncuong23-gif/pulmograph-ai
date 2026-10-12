"""Optional late fusion of frozen Text+Graph decision scores and X-ray outputs.

The base bias is retained *before* fusion. No-image calls return the base result
unchanged. Normalized decision weights are not calibrated disease probabilities.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from . import LABELS
from .hybrid import HybridClassifier, HybridPrediction, TopClass
from ..models import verify_bundle


def softmax(scores: np.ndarray) -> np.ndarray:
    scores = np.asarray(scores, dtype=np.float64)
    exp = np.exp(scores - np.max(scores, axis=-1, keepdims=True))
    return exp / exp.sum(axis=-1, keepdims=True)


def validate_image_probabilities(probabilities: np.ndarray) -> np.ndarray:
    p = np.asarray(probabilities, dtype=np.float64)
    if p.ndim not in (1, 2) or p.shape[-1] != len(LABELS) or not np.isfinite(p).all():
        raise ValueError("Invalid image probability shape or non-finite values")
    if np.any(p < 0) or not np.allclose(p.sum(axis=-1), 1.0, atol=1e-6, rtol=0):
        raise ValueError("Image probabilities must be nonnegative and sum to one")
    return p


def fuse_scores(base_scores: np.ndarray, image_probabilities: np.ndarray,
                *, image_weight: float, method: str) -> np.ndarray:
    s = np.asarray(base_scores, dtype=np.float64)
    p = validate_image_probabilities(image_probabilities)
    if s.shape != p.shape or not np.isfinite(s).all():
        raise ValueError("Base/image shape mismatch or non-finite base scores")
    if not np.isfinite(image_weight) or not 0 <= image_weight <= 1 or method not in ("linear", "log"):
        raise ValueError("Invalid fusion method or weight")
    if image_weight == 0:
        return s.copy()
    image_scores = np.log(np.maximum(p, 1e-12))
    if image_weight == 1:
        return image_scores
    if method == "log":
        return (1 - image_weight) * s + image_weight * image_scores
    mixture = (1 - image_weight) * softmax(s) + image_weight * p
    return np.log(np.maximum(mixture, 1e-12))


class LateFusionClassifier:
    """Drop-in classifier; image_path is an optional, same-case observation."""

    def __init__(self, base: HybridClassifier, checkpoint: str | Path, *,
                 image_weight: float, method: str, device: str = "auto",
                 checkpoint_sha256: str | None = None, image_predictor: Any = None):
        # Validate configuration even if this instance will only receive text.
        fuse_scores(np.zeros(len(LABELS)), np.full(len(LABELS), 1 / len(LABELS)),
                    image_weight=image_weight, method=method)
        self.base = base
        self.labels = base.labels
        self.checkpoint = Path(checkpoint)
        self.image_weight = float(image_weight)
        self.method = method
        self.device = device
        self.checkpoint_sha256 = checkpoint_sha256
        self._image_predictor = image_predictor
        self.metadata = {"inference_config": {"method": f"late_fusion_{method}",
                         "image_weight": self.image_weight, "base": base.metadata}}

    @classmethod
    def from_bundle(cls, bundle_dir: str | Path, *, device: str = "auto") -> LateFusionClassifier:
        root = Path(bundle_dir).resolve()
        manifest = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
        required = {"base/bundle.json", "base/text_branch.joblib", "base/graph_branch.joblib",
                    "base/bayes_branch.joblib", "image/convnext_tiny_model.pt"}
        if (manifest.get("classifier_type") != "late_fusion" or tuple(manifest.get("labels", [])) != LABELS
                or set(manifest.get("files", {})) != required):
            raise ValueError("Invalid/incomplete fusion manifest")
        if any(not (root / rel).resolve().is_relative_to(root) for rel in required):
            raise ValueError("Fusion asset path escapes bundle")
        info = verify_bundle(root)
        if not info.is_valid:
            raise ValueError(f"Invalid fusion bundle: {info.errors}")
        cfg = manifest["fusion"]
        return cls(HybridClassifier.from_bundle(root / "base"), root / "image/convnext_tiny_model.pt",
                   image_weight=cfg["image_weight"], method=cfg["method"], device=device,
                   checkpoint_sha256=manifest["files"]["image/convnext_tiny_model.pt"])

    def predict(self, text: str | None = None, graph: dict | None = None, *,
                image_path: str | Path | None = None,
                image_probabilities: np.ndarray | None = None) -> HybridPrediction:
        if image_path is not None and image_probabilities is not None:
            raise ValueError("Supply image_path OR already aligned image_probabilities, not both")
        base = self.base.predict(text=text, graph=graph)
        if image_path is None and image_probabilities is None:
            return base
        if image_probabilities is None:
            if self._image_predictor is None:
                from .xray import XrayClassifier
                self._image_predictor = XrayClassifier(self.checkpoint, device=self.device,
                                                       expected_sha256=self.checkpoint_sha256)
            image_probabilities = self._image_predictor.predict_proba(image_path)
        p = validate_image_probabilities(image_probabilities)
        if p.ndim != 1:
            raise ValueError("predict() expects one case, not a batch")
        only_image = base.status == "insufficient_information"
        scores = fuse_scores(np.array([base.all_scores[l] for l in LABELS]), p,
                             image_weight=1.0 if only_image else self.image_weight, method=self.method)
        normalized = softmax(scores)
        order = np.argsort(-scores)
        warnings = base.warnings + [
            "Có ảnh: điểm fusion là trọng số xếp hạng chưa hiệu chuẩn, không phải xác suất chẩn đoán.",
            "Người gọi phải bảo đảm ảnh và văn bản/đồ thị thuộc cùng ca bệnh; hệ thống không tự xác minh danh tính.",
        ]
        if only_image:
            warnings.append("Thiếu văn bản/đồ thị: chỉ dùng ảnh; trọng số chọn cho dữ liệu ghép cặp không áp dụng.")
        return HybridPrediction(
            top5=[TopClass(i + 1, LABELS[k], float(scores[k]), float(normalized[k])) for i, k in enumerate(order[:5])],
            all_scores=dict(zip(LABELS, map(float, scores))),
            all_probabilities=dict(zip(LABELS, map(float, normalized))),
            branch_probabilities={**base.branch_probabilities, "image": dict(zip(LABELS, map(float, p)))},
            is_empty_graph=base.is_empty_graph, is_empty_text=base.is_empty_text,
            status="fallback_image_only" if only_image else "late_fusion", warnings=warnings)
