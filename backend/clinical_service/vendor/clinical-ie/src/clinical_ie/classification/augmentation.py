"""Targeted feature-space data augmentation for extreme rare disease classes."""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy import sparse


def augment_training_features(
    X_train: sparse.csr_matrix,
    y_train: np.ndarray,
    min_samples_per_class: int = 80,
    alpha: float = 0.4,
    random_state: int = 42,
) -> tuple[sparse.csr_matrix, np.ndarray]:
    """Augment sparse training feature matrix for rare classes using Clinical Feature Mixup.

    For any class with fewer than `min_samples_per_class` training instances,
    generates synthetic instances via convex combinations of existing within-class samples.
    """
    rng = np.random.default_rng(random_state)
    classes, counts = np.unique(y_train, return_counts=True)
    class_counts = dict(zip(classes, counts))

    X_aug_rows = [X_train]
    y_aug_list = [y_train]

    num_augmented_total = 0

    for c in classes:
        count = class_counts[c]
        if count >= min_samples_per_class:
            continue

        needed = min_samples_per_class - count
        c_indices = np.where(y_train == c)[0]
        if len(c_indices) == 0:
            continue

        # Extract submatrix for class c in CSR format
        X_c = X_train[c_indices]

        # Generate `needed` synthetic samples
        synthetic_rows = []
        for _ in range(needed):
            # Pick two distinct samples from class c (or same if only 1 exists)
            i1 = rng.integers(0, len(c_indices))
            i2 = rng.integers(0, len(c_indices))
            row1 = X_c[i1]
            row2 = X_c[i2]

            lam = float(rng.beta(alpha, alpha))
            # Keep lambda in [0.2, 0.8] to ensure meaningful feature blending
            lam = min(max(lam, 0.25), 0.75)

            syn_row = lam * row1 + (1.0 - lam) * row2
            synthetic_rows.append(syn_row)

        if synthetic_rows:
            X_syn = sparse.vstack(synthetic_rows)
            y_syn = np.full(needed, c, dtype=y_train.dtype)

            X_aug_rows.append(X_syn)
            y_aug_list.append(y_syn)
            num_augmented_total += needed

    if num_augmented_total > 0:
        X_res = sparse.vstack(X_aug_rows).tocsr()
        y_res = np.concatenate(y_aug_list)
        print(f"   [Augmentation] Added {num_augmented_total} synthetic instances for rare classes (New train shape: {X_res.shape}).")
        return X_res, y_res

    return X_train, y_train
