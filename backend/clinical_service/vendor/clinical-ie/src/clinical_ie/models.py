"""Bundle verification, device detection, and offline asset resolution."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Repository CLI default, relative to the caller's working directory. Explicit
# bundle paths remain required for portable Python API / handover deployments.
DEFAULT_CLASSIFIER_BUNDLE = Path("dist/classifier-bundle-v2")


@dataclass(frozen=True)
class BundleInfo:
    bundle_name: str
    bundle_dir: str
    version: str
    is_valid: bool
    files: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_name": self.bundle_name,
            "bundle_dir": self.bundle_dir,
            "version": self.version,
            "is_valid": self.is_valid,
            "files": self.files,
            "errors": self.errors,
            "metadata": self.metadata,
        }


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_bundle(
    bundle_dir: str | Path,
    expected_name: str | None = None,
    *,
    expected_kind: str | None = None,
) -> BundleInfo:
    """Offline verification of manifest checksums and integrity for any model/data bundle."""
    b_path = Path(bundle_dir).resolve()
    if not b_path.is_dir():
        return BundleInfo(
            bundle_name=expected_name or "unknown",
            bundle_dir=str(b_path),
            version="unknown",
            is_valid=False,
            errors=[f"Directory does not exist: {b_path}"],
        )

    # Manifest file can be bundle.json or manifest.json
    manifest_file = b_path / "bundle.json"
    if not manifest_file.is_file():
        manifest_file = b_path / "manifest.json"

    if not manifest_file.is_file():
        return BundleInfo(
            bundle_name=expected_name or b_path.name,
            bundle_dir=str(b_path),
            version="unknown",
            is_valid=False,
            errors=[f"Missing manifest file (bundle.json or manifest.json) in {b_path}"],
        )

    try:
        with manifest_file.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except Exception as exc:
        return BundleInfo(
            bundle_name=expected_name or b_path.name,
            bundle_dir=str(b_path),
            version="unknown",
            is_valid=False,
            errors=[f"Failed to parse manifest JSON: {exc}"],
        )

    if not isinstance(manifest, dict):
        return BundleInfo(b_path.name, str(b_path), "unknown", False,
                          errors=["Manifest must be a JSON object"])
    bundle_name = manifest.get("bundle_name", manifest.get("name", b_path.name))
    version = manifest.get("version", manifest.get("schema_version", "1.0"))
    errors: list[str] = []

    if expected_name and bundle_name != expected_name:
        errors.append(f"Bundle name mismatch: expected '{expected_name}', got '{bundle_name}'")

    file_hashes = manifest.get("files")
    verified_files: dict[str, str] = {}
    if not isinstance(file_hashes, dict) or not file_hashes:
        errors.append("Manifest files must be a non-empty checksum mapping")
        file_hashes = {}

    if manifest.get("classifier_type") == "late_fusion":
        kind = "fusion"
    elif "labels" in manifest or "text_branch.joblib" in file_hashes:
        kind = "classifier"
    elif "reference_cases.jsonl" in file_hashes or str(bundle_name).startswith("reference-index"):
        kind = "reference_index"
    elif str(bundle_name).startswith("clinical-ie-models") or any(k.startswith("simplifier/") for k in file_hashes if isinstance(k, str)):
        kind = "ie"
    else:
        kind = "generic"
    if expected_kind and kind not in ({"classifier", "fusion"} if expected_kind == "classifier" else {expected_kind}):
        errors.append(f"Wrong bundle kind: expected {expected_kind}, got {kind}")
    required = {
        "classifier": {"text_branch.joblib", "graph_branch.joblib", "bayes_branch.joblib"},
        "fusion": {"base/bundle.json", "base/text_branch.joblib", "base/graph_branch.joblib",
                   "base/bayes_branch.joblib", "image/convnext_tiny_model.pt"},
        "reference_index": {"reference_cases.jsonl"},
        "ie": {"simplifier/metrics.json", "simplifier/run_config.json",
               "simplifier/final_model/config.json", "joint/metrics.json", "joint/run_config.json",
               "joint/final_model/gliner_config.json"},
    }.get(kind, set())
    for name in sorted(required - file_hashes.keys()):
        errors.append(f"Missing required manifest file: {name}")
    if kind == "ie":
        for component in ("joint", "simplifier"):
            if not any(f"{component}/final_model/{name}" in file_hashes for name in ("model.safetensors", "pytorch_model.bin")):
                errors.append(f"Missing required model weights: {component}")
            if not any(f"{component}/final_model/{name}" in file_hashes for name in ("tokenizer.json", "spiece.model", "spm.model")):
                errors.append(f"Missing required tokenizer: {component}")
    if kind in {"classifier", "fusion"}:
        from .classification import LABELS
        if manifest.get("labels") != list(LABELS):
            errors.append("Classifier label order does not match the 12 supported classes")
    if kind == "fusion":
        cfg = manifest.get("fusion")
        weight = cfg.get("image_weight") if isinstance(cfg, dict) else None
        if (not isinstance(cfg, dict) or cfg.get("method") not in {"linear", "log"}
                or isinstance(weight, bool) or not isinstance(weight, (int, float)) or not 0 <= weight <= 1):
            errors.append("Invalid fusion configuration")
    if kind == "reference_index" and manifest.get("split") != "train_only":
        errors.append("Reference index must be train_only")

    for rel_path, expected_hash in file_hashes.items():
        if (not isinstance(rel_path, str) or not rel_path or "\\" in rel_path
                or Path(rel_path).is_absolute() or ".." in Path(rel_path).parts
                or not (b_path / rel_path).resolve().is_relative_to(b_path)):
            errors.append(f"Unsafe manifest path: {rel_path}")
            continue
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            errors.append(f"Invalid SHA-256 digest for: {rel_path}")
            continue
        file_path = b_path / rel_path
        if not file_path.is_file():
            errors.append(f"Missing file specified in manifest: {rel_path}")
            continue
        try:
            actual_hash = sha256_file(file_path)
        except OSError as exc:
            errors.append(f"Cannot read {rel_path}: {exc}")
            continue
        verified_files[rel_path] = actual_hash
        if actual_hash != expected_hash:
            errors.append(
                f"Checksum mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}"
            )

    return BundleInfo(
        bundle_name=bundle_name,
        bundle_dir=str(b_path),
        version=version,
        is_valid=len(errors) == 0,
        files=verified_files,
        errors=errors,
        metadata=manifest.get("metadata", {}),
    )


def resolve_device(requested: str = "auto") -> str:
    """Determine compute device ('cpu', 'mps', 'cuda') safely with fallback warnings."""
    req = (requested or "auto").lower().strip()
    if req not in ("auto", "cpu", "mps", "cuda"):
        print(f"Cảnh báo: Yêu cầu thiết bị không hợp lệ '{requested}'; dùng mặc định 'auto'.", file=sys.stderr)
        req = "auto"

    try:
        import torch
    except ImportError:
        return "cpu"

    if req == "cuda":
        if torch.cuda.is_available():
            return "cuda"
        print("Cảnh báo: CUDA không khả dụng trên máy này; chuyển về 'cpu'.", file=sys.stderr)
        return "cpu"

    if req == "mps":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        print("Cảnh báo: Apple Silicon MPS không khả dụng trên máy này; chuyển về 'cpu'.", file=sys.stderr)
        return "cpu"

    if req == "cpu":
        return "cpu"

    # auto
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def enforce_offline_environment() -> None:
    """Set standard offline environment flags for air-gapped or non-network execution."""
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
