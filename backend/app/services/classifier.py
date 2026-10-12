from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np


class E5SVMClassifier:
    """Lazy E5 encoder + uploaded sklearn SVM model adapter."""

    def __init__(
        self,
        model_path: Path,
        embedding_model: str,
        id2label: dict[str, str],
        embedding_prefix: str = "query: ",
        normalize_embeddings: bool = True,
        device: str = "auto",
        revision: str | None = None,
    ) -> None:
        self.device, self.revision = device, revision
        self.model_path = model_path
        self.embedding_model_name = embedding_model
        self.id2label = {str(k): str(v) for k, v in id2label.items()}
        self.embedding_prefix = embedding_prefix
        self.normalize_embeddings = normalize_embeddings
        self._lock = threading.Lock()
        self._model: Any = None
        self._encoder: Any = None

    def _load(self) -> None:
        if self._model is not None and self._encoder is not None:
            return
        with self._lock:
            if self._model is not None and self._encoder is not None:
                return
            if not self.model_path.is_file():
                raise RuntimeError(f"Classifier artifact not found: {self.model_path}")
            import joblib
            from .encoders import get_encoder

            model = joblib.load(self.model_path)
            encoder = get_encoder(self.embedding_model_name, revision=self.revision, device=self.device)
            expected = getattr(model, "n_features_in_", None)
            actual = encoder.get_sentence_embedding_dimension()
            if expected is not None and int(expected) != int(actual):
                raise RuntimeError(
                    f"Embedding dimension mismatch: classifier expects {expected}, encoder returns {actual}"
                )
            self._model, self._encoder = model, encoder

    @staticmethod
    def _label_key(value: Any) -> str:
        if isinstance(value, (int, np.integer)):
            return str(int(value))
        return str(value)

    def predict(self, text: str) -> dict[str, Any]:
        self._load()
        encoded_text = f"{self.embedding_prefix}{text}" if self.embedding_prefix else text
        vector = self._encoder.encode(
            [encoded_text],
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
        )
        prediction = self._model.predict(vector)[0]
        key = self._label_key(prediction)
        label = self.id2label.get(key, key)

        margin = None
        if hasattr(self._model, "decision_function"):
            scores = np.asarray(self._model.decision_function(vector)).reshape(-1)
            if scores.size > 1:
                sorted_scores = np.sort(scores)
                margin = float(sorted_scores[-1] - sorted_scores[-2])
            elif scores.size == 1:
                margin = float(abs(scores[0]))
        return {"label": label, "class_id": key, "decision_margin": margin}
