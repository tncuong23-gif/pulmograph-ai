"""Dataset loader for disease classification from graphs and prediagnosis text."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import LABELS, LABEL_TO_ID

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GRAPH_DIR = ROOT / "artifacts" / "corpus" / "full_v2_simple_v13_mps_r1_entity_dedup_v1" / "graphs"
DEFAULT_TARGETS_DIR = ROOT / "artifacts" / "classification" / "prediagnosis_v2" / "split_targets"
DEFAULT_TEXT_DIR = ROOT / "artifacts" / "classification" / "prediagnosis_v2" / "splits"


@dataclass(frozen=True)
class ClassificationRecord:
    doc_id: str
    label: str
    class_id: int
    graph: dict[str, Any]
    text: str | None = None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_split(
    split: str,
    *,
    graph_dir: Path | str = DEFAULT_GRAPH_DIR,
    targets_dir: Path | str = DEFAULT_TARGETS_DIR,
    text_dir: Path | str | None = DEFAULT_TEXT_DIR,
) -> list[ClassificationRecord]:
    """Load aligned graph, target, and optional text for a split (train/validation/test)."""
    graph_path = Path(graph_dir) / f"{split}.jsonl"
    target_path = Path(targets_dir) / f"{split}.jsonl"
    text_path = Path(text_dir) / f"{split}.jsonl" if text_dir else None

    if not graph_path.is_file():
        raise FileNotFoundError(f"Missing graph split file: {graph_path}")
    if not target_path.is_file():
        raise FileNotFoundError(f"Missing target split file: {target_path}")

    graph_rows = _load_jsonl(graph_path)
    target_rows = _load_jsonl(target_path)
    text_rows = _load_jsonl(text_path) if text_path and text_path.is_file() else []

    target_map = {row["doc_id"]: row for row in target_rows}
    text_map = {row["doc_id"]: row["text"] for row in text_rows} if text_rows else {}

    if len(graph_rows) != len(target_rows):
        raise ValueError(
            f"Split {split} count mismatch: {len(graph_rows)} graphs vs {len(target_rows)} targets"
        )

    records: list[ClassificationRecord] = []
    for graph in graph_rows:
        doc_id = graph["doc_id"]
        if doc_id not in target_map:
            raise KeyError(f"Target missing for doc_id {doc_id} in split {split}")
        tgt = target_map[doc_id]
        label = tgt["label"]
        class_id = tgt.get("class_id", LABEL_TO_ID.get(label))
        if label not in LABEL_TO_ID:
            raise ValueError(f"Unknown label {label!r} for doc_id {doc_id}")

        records.append(
            ClassificationRecord(
                doc_id=doc_id,
                label=label,
                class_id=class_id,
                graph=graph,
                text=text_map.get(doc_id),
            )
        )

    return records


def load_all_splits(
    *,
    graph_dir: Path | str = DEFAULT_GRAPH_DIR,
    targets_dir: Path | str = DEFAULT_TARGETS_DIR,
    text_dir: Path | str | None = DEFAULT_TEXT_DIR,
) -> dict[str, list[ClassificationRecord]]:
    """Load train, validation, and test splits with strict disjoint verification."""
    splits = {}
    seen_doc_ids: set[str] = set()
    for name in ("train", "validation", "test"):
        split_records = load_split(
            name,
            graph_dir=graph_dir,
            targets_dir=targets_dir,
            text_dir=text_dir,
        )
        current_ids = {r.doc_id for r in split_records}
        overlap = seen_doc_ids.intersection(current_ids)
        if overlap:
            raise ValueError(f"Data leakage detected: {len(overlap)} doc_ids overlap with {name}")
        seen_doc_ids.update(current_ids)
        splits[name] = split_records

    return splits
