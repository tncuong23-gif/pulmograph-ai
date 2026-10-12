"""Offline ConvNeXt inference using the exact preprocessing saved by the Colab run.

Vision dependencies are optional and imported only when an image is supplied.
No ImageNet downloads, no unsafe checkpoint unpickling, no inference augmentation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np

from . import LABELS
from ..models import resolve_device, sha256_file

PREPROCESSING = "grayscale->3ch; full-frame square bilinear resize; normalize; no center crop"


class XrayClassifier:
    def __init__(self, checkpoint: str | Path, *, device: str = "auto", expected_sha256: str | None = None):
        import torch
        from torchvision import models, transforms
        from torchvision.transforms import InterpolationMode

        self.checkpoint = Path(checkpoint).resolve()
        if not self.checkpoint.is_file():
            raise FileNotFoundError(self.checkpoint)
        self.sha256 = sha256_file(self.checkpoint)
        if expected_sha256 is not None and self.sha256 != expected_sha256:
            raise ValueError("X-ray checkpoint checksum mismatch")
        saved = torch.load(self.checkpoint, map_location="cpu", weights_only=True)
        self.metadata = saved["metadata"]
        m = self.metadata
        if (m.get("model_name") != "convnext_tiny" or m.get("num_classes") != len(LABELS)
                or tuple(m.get("class_names", [])) != LABELS):
            raise ValueError("Unsupported architecture or X-ray label order mismatch")
        if (m.get("preprocessing") != PREPROCESSING or m.get("image_size") != 224
                or m.get("mean") != [0.485, 0.456, 0.406] or m.get("std") != [0.229, 0.224, 0.225]):
            raise ValueError("Checkpoint preprocessing does not match the validated Colab protocol")
        model = models.convnext_tiny(weights=None)
        model.classifier[-1] = torch.nn.Linear(model.classifier[-1].in_features, len(LABELS))
        model.load_state_dict(saved["state_dict"], strict=True)
        self.device = resolve_device(device)
        self.model = model.to(self.device).eval()
        self.transform = transforms.Compose([
            transforms.Grayscale(num_output_channels=3),
            transforms.Resize((224, 224), interpolation=InterpolationMode.BILINEAR, antialias=True),
            transforms.ToTensor(), transforms.Normalize(m["mean"], m["std"]),
        ])

    def predict_logits(self, paths: Sequence[str | Path]) -> np.ndarray:
        import torch
        from PIL import Image

        if not paths:
            return np.empty((0, len(LABELS)), dtype=np.float32)
        tensors = []
        for path in paths:
            with Image.open(Path(path)) as img:
                tensors.append(self.transform(img))
        batch = torch.stack(tensors).to(self.device)
        with torch.inference_mode():
            logits = self.model(batch).float().cpu().numpy()
        if logits.shape != (len(paths), len(LABELS)) or not np.isfinite(logits).all():
            raise ValueError("Invalid X-ray logits")
        return logits

    def predict_proba(self, path: str | Path) -> np.ndarray:
        logits = self.predict_logits([path]).astype(np.float64)[0]
        exp = np.exp(logits - logits.max())
        return exp / exp.sum()
