"""Clinical transformer text encoder with disk-based embedding caching."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from .dataset import ClassificationRecord

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = ROOT / "artifacts" / "cache" / "text_embeddings"


def _sanitize_model_name(name: str) -> str:
    return re.sub(r"[^\w\-_.]", "_", name)


def mean_pooling(model_output: Any, attention_mask: torch.Tensor) -> torch.Tensor:
    """Mean pooling over token embeddings taking attention mask into account."""
    token_embeddings = model_output[0]  # First element of model_output contains hidden states
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
    sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
    return sum_embeddings / sum_mask


def extract_embeddings_for_texts(
    texts: list[str],
    model_name: str = "vinai/phobert-base-v2",
    batch_size: int = 32,
    max_length: int = 256,
    device: str | None = None,
) -> np.ndarray:
    """Extract dense 768-dimensional contextual embeddings from clinical texts."""
    if device is None:
        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"

    print(f"Loading pretrained clinical language model: {model_name} on {device}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    model.to(device)
    model.eval()

    all_embeddings: list[np.ndarray] = []
    num_samples = len(texts)

    with torch.no_grad():
        for start_idx in range(0, num_samples, batch_size):
            batch_texts = texts[start_idx : start_idx + batch_size]
            # Replace empty strings with a single space to avoid tokenizer issues
            batch_texts = [t if t.strip() else " " for t in batch_texts]

            encoded = tokenizer(
                batch_texts,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            ).to(device)

            outputs = model(**encoded)
            pooled = mean_pooling(outputs, encoded["attention_mask"])
            all_embeddings.append(pooled.cpu().numpy())

    return np.vstack(all_embeddings).astype(np.float32)


def get_or_extract_split_embeddings(
    split_name: str,
    records: list[ClassificationRecord],
    model_name: str = "vinai/phobert-base-v2",
    cache_dir: Path | None = None,
    batch_size: int = 32,
    max_length: int = 256,
    force_recompute: bool = False,
) -> np.ndarray:
    """Retrieve embeddings from disk cache if present, otherwise compute and cache."""
    cache_path = (cache_dir or DEFAULT_CACHE_DIR) / f"{_sanitize_model_name(model_name)}_{split_name}.npy"
    if cache_path.is_file() and not force_recompute:
        loaded = np.load(cache_path)
        if len(loaded) == len(records):
            print(f"Loaded cached text embeddings for '{split_name}' from: {cache_path} (shape: {loaded.shape})")
            return loaded

    print(f"Computing embeddings for '{split_name}' ({len(records)} records)...")
    texts = [r.text or "" for r in records]
    embeddings = extract_embeddings_for_texts(
        texts,
        model_name=model_name,
        batch_size=batch_size,
        max_length=max_length,
    )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache_path, embeddings)
    print(f"Saved text embeddings to: {cache_path}")
    return embeddings
