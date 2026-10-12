import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import argparse
import json
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Iterable

from .preprocess import collect_section_counts, group_by_content, parse_document
from .rules import preannotate_segment
from .sampling import build_candidate_pool, choose_seed, sample_pilot, sampling_report
from .schema import load_schema
from .simplification import (
    ANNOTATION_METHOD,
    SENTENCE_CLOSE,
    SENTENCE_OPEN,
    audit_simplification,
    decompose_record,
    seq2seq_row,
)
from .training import (
    ENTITY_LABELS,
    LEARNED_RELATIONS,
    conversion_index,
    grouped_stratified_split,
    oversample_rare_relation_records,
    promote_proxy_gold,
    sha256_file,
    summarize_records,
    to_gliner_record,
)
from .validate import read_jsonl, validate_records
from .models import DEFAULT_CLASSIFIER_BUNDLE


from .schema import get_default_schema_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = get_default_schema_path()


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _atomic_write_jsonl(path: Path, records: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            count += 1
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return count


def prepare(args: argparse.Namespace) -> int:
    input_root = Path(args.input).resolve()
    output_root = Path(args.output).resolve()
    if not input_root.is_dir():
        raise SystemExit(f"Input directory not found: {input_root}")

    paths = sorted(input_root.rglob("*.txt"))
    parsed = []
    failures: list[dict] = []
    for path in paths:
        try:
            parsed.append(parse_document(path, input_root))
        except Exception as exc:  # keep the batch auditable instead of silently skipping
            failures.append({"source_path": path.relative_to(input_root).as_posix(), "error": str(exc)})

    nonempty_documents = [document for document in parsed if document.text.strip()]
    documents, duplicate_groups = group_by_content(nonempty_documents)
    processed_dir = output_root / "processed"
    pilot_dir = output_root / "pilot"
    report_dir = output_root / "reports"
    private_dir = output_root / "private"

    _atomic_write_jsonl(processed_dir / "documents.jsonl", documents)
    _atomic_write_jsonl(processed_dir / "dedup_groups.jsonl", duplicate_groups)
    _atomic_write_jsonl(
        private_dir / "document_manifest.jsonl",
        (
            {
                "doc_id": item.doc_id,
                "source_path": item.relative_path,
                "disease": item.disease,
                "content_hash": item.content_hash,
                "pii_counts": item.pii_counts,
            }
            for item in parsed
        ),
    )
    if failures:
        _atomic_write_jsonl(private_dir / "parse_failures.jsonl", failures)

    candidate_pool = build_candidate_pool(documents)
    pilot = sample_pilot(
        candidate_pool,
        size=args.pilot_size,
        negative_ratio=args.negative_ratio,
        seed=args.seed,
    )
    seed_records = choose_seed(pilot, min(args.seed_size, len(pilot)), seed=args.seed)
    _atomic_write_jsonl(pilot_dir / "pilot_preannotated.jsonl", pilot)
    _atomic_write_jsonl(pilot_dir / "pilot_seed.jsonl", seed_records)

    schema = load_schema(args.schema)
    validation = validate_records(pilot, schema)
    _atomic_write_json(report_dir / "pilot_validation.json", validation)

    original_classes = Counter(item.disease for item in parsed)
    unique_classes: Counter[str] = Counter()
    pii_counts: Counter[str] = Counter()
    for document in documents:
        unique_classes.update(document["disease_labels"])
        pii_counts.update(document.get("pii_counts", {}))

    audit = {
        "input_root": str(input_root),
        "txt_files": len(paths),
        "parsed_files": len(parsed),
        "parse_failures": len(failures),
        "empty_documents": len(parsed) - len(nonempty_documents),
        "unique_documents": len(documents),
        "duplicate_groups": len(duplicate_groups),
        "redundant_copies": len(nonempty_documents) - len(documents),
        "cross_label_duplicate_groups": sum(group["label_conflict"] for group in duplicate_groups),
        "original_class_counts": dict(original_classes.most_common()),
        "unique_class_counts": dict(unique_classes.most_common()),
        "section_counts": dict(collect_section_counts(documents).most_common()),
        "pii_redactions": dict(pii_counts.most_common()),
        "candidate_segments": len(candidate_pool),
        "pilot": sampling_report(pilot),
        "pilot_validation": validation,
        "privacy_note": "Only artifacts/processed and artifacts/pilot are eligible for Colab after review. Keep artifacts/private local.",
    }
    _atomic_write_json(report_dir / "audit.json", audit)

    print(json.dumps({
        "parsed_files": len(parsed),
        "unique_documents": len(documents),
        "pilot_segments": len(pilot),
        "invalid_pilot_records": validation["invalid_records"],
        "output": str(output_root),
    }, ensure_ascii=False, indent=2))
    return 0 if validation["invalid_records"] == 0 else 2


def validate(args: argparse.Namespace) -> int:
    schema = load_schema(args.schema)
    report = validate_records(read_jsonl(args.input), schema)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["invalid_records"] == 0 else 2


def _annotation_counts(records: Iterable[dict]) -> dict[str, dict[str, int] | int]:
    entity_counts: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()
    total = 0
    needs_review = 0
    for record in records:
        total += 1
        needs_review += bool(record.get("needs_review"))
        entity_counts.update(entity["label"] for entity in record.get("entities", []))
        relation_counts.update(relation["predicate"] for relation in record.get("relations", []))
    return {
        "records": total,
        "needs_human_review": needs_review,
        "entity_counts": dict(entity_counts.most_common()),
        "relation_counts": dict(relation_counts.most_common()),
    }


def refresh(args: argparse.Namespace) -> int:
    source_records = list(read_jsonl(args.input))
    refreshed: list[dict] = []
    for source in source_records:
        record = preannotate_segment(source)
        record["annotation_status"] = args.status
        record["review_notes"] = args.review_note
        if args.accept_silver_as_gold:
            record["needs_review"] = False
            record["training_eligible"] = True
            record["gold_policy"] = "silver_accepted_as_gold_by_project_owner"
        record["review"] = {
            "reviewed_by": args.reviewer,
            "reviewed_at": date.today().isoformat(),
            "method": args.method,
            "human_validation_required": not args.accept_silver_as_gold,
            "clinical_expert_validated": False,
        }
        refreshed.append(record)

    _atomic_write_jsonl(Path(args.output), refreshed)
    schema = load_schema(args.schema)
    validation = validate_records(refreshed, schema)
    report = {
        "input": str(Path(args.input).resolve()),
        "output": str(Path(args.output).resolve()),
        "status": args.status,
        "before": _annotation_counts(source_records),
        "after": _annotation_counts(refreshed),
        "validation": validation,
        "human_validation_required": not args.accept_silver_as_gold,
        "gold_policy": (
            "silver_accepted_as_gold_by_project_owner"
            if args.accept_silver_as_gold else None
        ),
    }
    if args.report:
        _atomic_write_json(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if validation["invalid_records"] == 0 else 2


def expand(args: argparse.Namespace) -> int:
    documents = list(read_jsonl(args.documents))
    candidates = build_candidate_pool(documents)
    excluded_hashes: set[str] = set()
    if args.exclude:
        excluded_hashes = {
            record["segment_hash"]
            for record in read_jsonl(args.exclude)
            if record.get("segment_hash")
        }
    available = [
        record for record in candidates if record.get("segment_hash") not in excluded_hashes
    ]
    selected = sample_pilot(
        available,
        size=min(args.size, len(available)),
        negative_ratio=args.negative_ratio,
        seed=args.seed,
    )
    for record in selected:
        record["annotation_batch"] = "EXPANDED_SILVER"

    _atomic_write_jsonl(Path(args.output), selected)
    schema = load_schema(args.schema)
    validation = validate_records(selected, schema)
    report = {
        "documents": len(documents),
        "candidate_segments": len(candidates),
        "excluded_reviewed_segments": len(excluded_hashes),
        "eligible_segments": len(available),
        "selected": sampling_report(selected),
        "validation": validation,
        "human_validation_required": True,
    }
    if args.report:
        _atomic_write_json(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if validation["invalid_records"] == 0 else 2


def build_training(args: argparse.Namespace) -> int:
    reviewed_path = Path(args.reviewed).resolve()
    expanded_path = Path(args.expanded).resolve()
    output_root = Path(args.output).resolve()
    schema_path = Path(args.schema).resolve()

    source_records = list(read_jsonl(reviewed_path)) + list(read_jsonl(expanded_path))
    proxy_gold = promote_proxy_gold(source_records)
    schema = load_schema(schema_path)
    validation = validate_records(proxy_gold, schema)
    if validation["invalid_records"]:
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 2

    splits = grouped_stratified_split(
        proxy_gold,
        train_ratio=args.train_ratio,
        dev_ratio=args.dev_ratio,
        test_ratio=args.test_ratio,
        seed=args.seed,
    )

    gold_dir = output_root / "gold"
    split_dir = gold_dir / "splits"
    training_dir = output_root / "training"
    ner_dir = training_dir / "ner"
    relex_dir = training_dir / "relex"
    index_dir = training_dir / "index"
    report_dir = output_root / "reports"

    gold_path = gold_dir / f"proxy_gold_v{args.version}.jsonl"
    _atomic_write_jsonl(gold_path, proxy_gold)

    generated_files: list[Path] = [gold_path]
    balanced_relex_records: list[dict] | None = None
    for split_name in ("train", "dev", "test"):
        records = splits[split_name]
        split_path = split_dir / f"{split_name}.jsonl"
        ner_path = ner_dir / f"{split_name}.json"
        relex_path = relex_dir / f"{split_name}.json"
        index_path = index_dir / f"{split_name}.jsonl"

        _atomic_write_jsonl(split_path, records)
        _atomic_write_json(
            ner_path,
            [to_gliner_record(record, include_relations=False) for record in records],
        )
        _atomic_write_json(
            relex_path,
            [to_gliner_record(record, include_relations=True) for record in records],
        )
        _atomic_write_jsonl(index_path, conversion_index(records))
        generated_files.extend((split_path, ner_path, relex_path, index_path))

        if split_name == "train":
            balanced_relex_records = oversample_rare_relation_records(
                records,
                minimum_relations=120,
                seed=args.seed,
            )
            balanced_path = relex_dir / "train_balanced.json"
            balanced_index_path = index_dir / "relex_train_balanced.jsonl"
            _atomic_write_json(
                balanced_path,
                [
                    to_gliner_record(record, include_relations=True)
                    for record in balanced_relex_records
                ],
            )
            _atomic_write_jsonl(
                balanced_index_path,
                conversion_index(balanced_relex_records),
            )
            generated_files.extend((balanced_path, balanced_index_path))

    if balanced_relex_records is None:
        raise RuntimeError("Training split was not generated")

    manifest = {
        "proxy_gold_version": args.version,
        "gold_policy": "silver_accepted_as_gold_by_project_owner",
        "created_at": date.today().isoformat(),
        "seed": args.seed,
        "split_ratios": {
            "train": args.train_ratio,
            "dev": args.dev_ratio,
            "test": args.test_ratio,
        },
        "split_strategy": {
            "group": "doc_id",
            "primary_strata": "disease_labels",
            "rare_learned_relation_priority_below_count": 100,
        },
        "schema": {
            "path": str(schema_path),
            "version": schema.raw.get("version"),
            "sha256": sha256_file(schema_path),
        },
        "source_files": {
            "reviewed": {"path": str(reviewed_path), "sha256": sha256_file(reviewed_path)},
            "expanded": {"path": str(expanded_path), "sha256": sha256_file(expanded_path)},
        },
        "labels": {
            "entities": list(ENTITY_LABELS),
            "learned_relations": list(LEARNED_RELATIONS),
            "derived_case_relations_are_excluded": True,
        },
        "validation": validation,
        "all": summarize_records(proxy_gold),
        "splits": {name: summarize_records(records) for name, records in splits.items()},
        "relation_train_balancing": {
            "method": "repeat_train_only_records_with_rare_learned_relations",
            "minimum_observed_relations": 120,
            "raw": summarize_records(splits["train"]),
            "balanced": summarize_records(balanced_relex_records),
            "unique_segment_hashes": len({
                record["segment_hash"] for record in balanced_relex_records
            }),
        },
        "leakage": {
            "doc_id_overlap": 0,
            "segment_hash_overlap": 0,
        },
        "generated_files": {
            str(path.relative_to(output_root)): {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in generated_files
        },
    }
    manifest_path = report_dir / "training_manifest.json"
    _atomic_write_json(manifest_path, manifest)
    print(json.dumps({
        "proxy_gold_records": len(proxy_gold),
        "splits": {name: len(records) for name, records in splits.items()},
        "invalid_records": validation["invalid_records"],
        "manifest": str(manifest_path),
    }, ensure_ascii=False, indent=2))
    return 0


def build_simple_training(args: argparse.Namespace) -> int:
    input_root = Path(args.input).resolve()
    output_root = Path(args.output).resolve()
    schema = load_schema(args.schema)
    generated_files: list[Path] = []
    split_reports: dict[str, dict] = {}
    all_pair_ids: dict[str, set[str]] = {}
    all_doc_ids: dict[str, set[str]] = {}

    annotations_dir = output_root / "annotations"
    seq2seq_dir = output_root / "seq2seq"
    simple_split_dir = output_root / "gold" / "splits"
    relex_dir = output_root / "training" / "relex"
    index_dir = output_root / "training" / "index"

    train_simple_records: list[dict] | None = None
    split_names = ["train", "dev", "test"]
    if (input_root / "legacy_dev.jsonl").is_file():
        split_names.append("legacy_dev")
    for split_name in split_names:
        source_path = input_root / f"{split_name}.jsonl"
        if not source_path.is_file():
            raise SystemExit(f"Không thấy split nguồn: {source_path}")
        source_records = list(read_jsonl(source_path))
        pairs: list[dict] = []
        simple_records: list[dict] = []
        for record in source_records:
            pair, sentences = decompose_record(record)
            pairs.append(pair)
            simple_records.extend(sentences)

        validation = validate_records(simple_records, schema)
        audit = audit_simplification(pairs, simple_records)
        audit["validation"] = validation
        if validation["invalid_records"]:
            print(json.dumps({split_name: audit}, ensure_ascii=False, indent=2))
            return 2
        if any(
            audit[key] != 1.0
            for key in (
                "entity_coverage",
                "relation_coverage",
                "negation_preservation",
                "numeric_preservation",
                "qualitative_preservation",
            )
        ):
            print(json.dumps({split_name: audit}, ensure_ascii=False, indent=2))
            return 2

        annotation_path = annotations_dir / f"{split_name}.jsonl"
        seq2seq_path = seq2seq_dir / f"{split_name}.json"
        simple_path = simple_split_dir / f"{split_name}.jsonl"
        relex_path = relex_dir / f"{split_name}.json"
        index_path = index_dir / f"{split_name}.jsonl"
        _atomic_write_jsonl(annotation_path, pairs)
        _atomic_write_json(seq2seq_path, [seq2seq_row(pair) for pair in pairs])
        _atomic_write_jsonl(simple_path, simple_records)
        _atomic_write_json(
            relex_path,
            [to_gliner_record(record, include_relations=True) for record in simple_records],
        )
        _atomic_write_jsonl(index_path, conversion_index(simple_records))
        generated_files.extend((
            annotation_path,
            seq2seq_path,
            simple_path,
            relex_path,
            index_path,
        ))
        split_reports[split_name] = audit
        all_pair_ids[split_name] = {pair["pair_id"] for pair in pairs}
        all_doc_ids[split_name] = {pair["doc_id"] for pair in pairs}
        if split_name == "train":
            train_simple_records = simple_records

    if train_simple_records is None:
        raise RuntimeError("Không tạo được simple train split")

    for left, right in (("train", "dev"), ("train", "test"), ("dev", "test")):
        overlap = all_pair_ids[left] & all_pair_ids[right]
        if overlap:
            raise RuntimeError(f"Pair leakage {left}/{right}: {sorted(overlap)[:5]}")
        doc_overlap = all_doc_ids[left] & all_doc_ids[right]
        if doc_overlap:
            raise RuntimeError(f"Document leakage {left}/{right}: {sorted(doc_overlap)[:5]}")

    if "legacy_dev" in all_doc_ids:
        for other in ("train", "test"):
            doc_overlap = all_doc_ids["legacy_dev"] & all_doc_ids[other]
            if doc_overlap:
                raise RuntimeError(
                    f"Legacy-dev document leakage {other}: {sorted(doc_overlap)[:5]}"
                )

    balanced = oversample_rare_relation_records(
        train_simple_records,
        minimum_relations=args.minimum_relations,
        seed=args.seed,
    )
    balanced_path = relex_dir / "train_balanced.json"
    balanced_index_path = index_dir / "relex_train_balanced.jsonl"
    _atomic_write_json(
        balanced_path,
        [to_gliner_record(record, include_relations=True) for record in balanced],
    )
    _atomic_write_jsonl(balanced_index_path, conversion_index(balanced))
    generated_files.extend((balanced_path, balanced_index_path))

    manifest = {
        "version": args.version,
        "created_at": date.today().isoformat(),
        "source_split_root": str(input_root),
        "annotation_policy": {
            "status": "SILVER_SIMPLE_V1_3",
            "method": ANNOTATION_METHOD,
            "clinical_terms_are_not_paraphrased": True,
            "learned_relation_envelopes_are_not_split": True,
            "source_labels_are_not_model_inputs": True,
        },
        "simplifier_training": {
            "task": "supervised_complex_to_simple_seq2seq",
            "input_field": "input_text",
            "target_field": "target_text",
            "sentence_tokens": [SENTENCE_OPEN, SENTENCE_CLOSE],
            "uses_existing_vit5_vocabulary": True,
        },
        "joint_training": {
            "unit": "simple_sentence",
            "learned_relations": list(LEARNED_RELATIONS),
            "minimum_train_relation_count": args.minimum_relations,
            "raw_train": summarize_records(train_simple_records),
            "balanced_train": summarize_records(balanced),
        },
        "splits": split_reports,
        "leakage": {
            "source_pair_overlap": 0,
            "source_doc_split_preserved": True,
        },
        "generated_files": {
            str(path.relative_to(output_root)): {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in generated_files
        },
    }
    manifest_path = output_root / "reports" / "simple_training_manifest.json"
    _atomic_write_json(manifest_path, manifest)
    print(json.dumps({
        "output": str(output_root),
        "splits": {
            name: {
                "pairs": report["pairs"],
                "simple_sentences": report["simple_sentences"],
                "entity_coverage": report["entity_coverage"],
                "relation_coverage": report["relation_coverage"],
                "negation_preservation": report["negation_preservation"],
                "numeric_preservation": report["numeric_preservation"],
                "qualitative_preservation": report["qualitative_preservation"],
                "invalid_records": report["validation"]["invalid_records"],
            }
            for name, report in split_reports.items()
        },
        "balanced_train_sentences": len(balanced),
        "manifest": str(manifest_path),
    }, ensure_ascii=False, indent=2))
    return 0


def infer(args: argparse.Namespace) -> int:
    from .inference import (
        ClinicalIEExtractor,
        iter_document_shard,
        read_jsonl as read_inference_jsonl,
        resolve_joint_model_run,
        run_inference,
    )

    documents_path = Path(args.documents).resolve()
    if not documents_path.is_file():
        raise SystemExit(f"Documents JSONL not found: {documents_path}")
    model_run = resolve_joint_model_run(args.models_root, args.model_run)
    print(json.dumps({
        "model_run": str(model_run.run_dir),
        "entity_threshold": model_run.entity_threshold,
        "relation_threshold": model_run.relation_threshold,
        "requested_device": args.device,
    }, ensure_ascii=False, indent=2))

    extractor = ClinicalIEExtractor(
        model_run,
        device=args.device,
        batch_size=args.batch_size,
    )
    print(f"Thiết bị thực tế: {extractor.device}")
    report = run_inference(
        extractor,
        iter_document_shard(
            read_inference_jsonl(documents_path),
            shard_count=args.shard_count,
            shard_index=args.shard_index,
        ),
        args.output,
        input_path=documents_path,
        include_text=args.include_text,
        resume=args.resume,
        limit=args.limit,
        progress_every=args.progress_every,
        document_batch_size=args.document_batch_size,
    )
    report["shard_count"] = args.shard_count
    report["shard_index"] = args.shard_index
    _atomic_write_json(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def audit_inference(args: argparse.Namespace) -> int:
    from .inference import audit_inference_output

    report = audit_inference_output(
        args.output,
        args.documents,
        allow_partial=args.allow_partial,
    )
    if args.report:
        _atomic_write_json(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


def merge_inference(args: argparse.Namespace) -> int:
    from .inference import merge_inference_outputs

    report = merge_inference_outputs(args.inputs, args.output)
    if args.report:
        _atomic_write_json(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def demo(args: argparse.Namespace) -> int:
    from .inference import (
        DEFAULT_DEMO_TEXT,
        ClinicalIEExtractor,
        build_demo_document,
        format_demo_output,
        resolve_joint_model_run,
    )

    if args.file:
        raw_text = Path(args.file).read_text(encoding="utf-8-sig", errors="replace")
    elif args.text:
        raw_text = args.text
    else:
        raw_text = DEFAULT_DEMO_TEXT
    document = build_demo_document(raw_text, section=args.section)
    model_run = resolve_joint_model_run(args.models_root, args.model_run)
    print(f"Đang nạp model: {model_run.final_model_dir}")
    extractor = ClinicalIEExtractor(
        model_run,
        device=args.device,
        batch_size=args.batch_size,
    )
    print(f"Thiết bị: {extractor.device}\n")
    result = extractor.extract_document(document, include_text=True)
    print(format_demo_output(result))
    if args.json_output:
        _atomic_write_json(Path(args.json_output), result)
        print(f"\nJSON chi tiết: {Path(args.json_output).resolve()}")
    return 0


def simple_model_status(args: argparse.Namespace) -> int:
    from .simple_pipeline import model_status

    try:
        status = model_status(
            args.models_root,
            simplifier_run=args.simplifier_run,
            joint_run=args.joint_run,
        )
    except (FileNotFoundError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def simple_demo(args: argparse.Namespace) -> int:
    from .inference import DEFAULT_DEMO_TEXT, build_demo_document
    from .preprocess import iter_segments
    from .simple_pipeline import (
        SimpleJointPipeline,
        format_simple_demo,
        resolve_simple_joint_run,
        resolve_simplifier_run,
    )

    if args.file:
        raw_text = Path(args.file).read_text(encoding="utf-8-sig", errors="replace")
    elif args.text:
        raw_text = args.text
    else:
        raw_text = DEFAULT_DEMO_TEXT
    document = build_demo_document(raw_text, section=args.section)
    segments = list(iter_segments(document))
    try:
        simplifier_run = resolve_simplifier_run(args.models_root, args.simplifier_run)
        joint_run = resolve_simple_joint_run(args.models_root, args.joint_run)
    except (FileNotFoundError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"Simplifier: {simplifier_run.final_model_dir}")
    print(f"Simple joint: {joint_run.final_model_dir}")
    pipeline = SimpleJointPipeline(
        simplifier_run,
        joint_run,
        device=args.device,
        simplifier_batch_size=args.simplifier_batch_size,
        joint_batch_size=args.joint_batch_size,
        num_beams=args.num_beams,
    )
    print(f"Thiết bị: {pipeline.device}\n")
    results = pipeline.extract_segments(segments)
    for index, result in enumerate(results, start=1):
        if len(results) > 1:
            print(f"===== SEGMENT {index}/{len(results)} =====")
        print(format_simple_demo(result))
        if index < len(results):
            print()
    if args.json_output:
        payload: object = results[0] if len(results) == 1 else {
            "doc_id": document["doc_id"],
            "segments": results,
        }
        _atomic_write_json(Path(args.json_output), payload)
        print(f"\nJSON chi tiết: {Path(args.json_output).resolve()}")
    return 0


def evaluate_simple(args: argparse.Namespace) -> int:
    from .simple_pipeline import (
        SimpleJointPipeline,
        evaluate_end_to_end,
        resolve_simple_joint_run,
        resolve_simplifier_run,
    )

    test_path = Path(args.test).resolve()
    if not test_path.is_file():
        raise SystemExit(f"Test JSONL not found: {test_path}")
    records = list(read_jsonl(test_path))
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit phải lớn hơn 0")
        records = records[: args.limit]
    try:
        simplifier_run = resolve_simplifier_run(args.models_root, args.simplifier_run)
        joint_run = resolve_simple_joint_run(args.models_root, args.joint_run)
    except (FileNotFoundError, ValueError) as error:
        raise SystemExit(str(error)) from error
    pipeline = SimpleJointPipeline(
        simplifier_run,
        joint_run,
        device=args.device,
        simplifier_batch_size=args.simplifier_batch_size,
        joint_batch_size=args.joint_batch_size,
        num_beams=args.num_beams,
    )
    predictions = pipeline.extract_segments(records)
    e2e = evaluate_end_to_end(records, predictions)
    report = {
        "status": "EVALUATED",
        "test_data": str(test_path),
        "test_records": len(records),
        "device": pipeline.device,
        "inference_config": {
            "simplifier_batch_size": args.simplifier_batch_size,
            "joint_batch_size": args.joint_batch_size,
            "num_beams": args.num_beams,
        },
        "models": {
            "simplifier": str(simplifier_run.run_dir),
            "simple_joint": str(joint_run.run_dir),
        },
        "colab_reference": {
            "simplifier_test": simplifier_run.metrics.get(
                "legacy_test", simplifier_run.metrics.get("test")
            ),
            "oracle_simple_joint_entity": joint_run.metrics.get("test_entity_micro"),
            "oracle_simple_joint_relation": joint_run.metrics.get("test_relation_micro"),
        },
        "end_to_end": e2e,
    }
    _atomic_write_jsonl(Path(args.predictions), predictions)
    _atomic_write_json(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Vietnamese clinical IE preparation pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="Parse, anonymize, deduplicate and pre-annotate a pilot")
    prepare_parser.add_argument("--input", default=str(PROJECT_ROOT / "dataset" / "train"))
    prepare_parser.add_argument("--output", default=str(PROJECT_ROOT / "artifacts"))
    prepare_parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    prepare_parser.add_argument("--pilot-size", type=int, default=400)
    prepare_parser.add_argument("--seed-size", type=int, default=50)
    prepare_parser.add_argument("--negative-ratio", type=float, default=0.20)
    prepare_parser.add_argument("--seed", type=int, default=42)
    prepare_parser.set_defaults(handler=prepare)

    validate_parser = subparsers.add_parser("validate", help="Validate an annotated JSONL file")
    validate_parser.add_argument("--input", required=True)
    validate_parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    validate_parser.set_defaults(handler=validate)

    refresh_parser = subparsers.add_parser(
        "refresh",
        help="Re-run current rules on a fixed annotation set and attach review metadata",
    )
    refresh_parser.add_argument("--input", required=True)
    refresh_parser.add_argument("--output", required=True)
    refresh_parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    refresh_parser.add_argument("--report")
    refresh_parser.add_argument("--status", default="AI_REVIEWED")
    refresh_parser.add_argument("--reviewer", default="Codex AI")
    refresh_parser.add_argument(
        "--method",
        default="full_seed_semantic_review_plus_rule_adjudication_v0.2",
    )
    refresh_parser.add_argument(
        "--review-note",
        default="AI review completed; clinician validation is still required before gold use.",
    )
    refresh_parser.add_argument(
        "--accept-silver-as-gold",
        action="store_true",
        help="Mark rule annotations training-eligible under the project owner's proxy-gold policy",
    )
    refresh_parser.set_defaults(handler=refresh)

    expand_parser = subparsers.add_parser(
        "expand",
        help="Create a balanced expanded silver set from processed documents",
    )
    expand_parser.add_argument(
        "--documents",
        default=str(PROJECT_ROOT / "artifacts" / "processed" / "documents.jsonl"),
    )
    expand_parser.add_argument("--exclude")
    expand_parser.add_argument("--output", required=True)
    expand_parser.add_argument("--report")
    expand_parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    expand_parser.add_argument("--size", type=int, default=1200)
    expand_parser.add_argument("--negative-ratio", type=float, default=0.20)
    expand_parser.add_argument("--seed", type=int, default=84)
    expand_parser.set_defaults(handler=expand)

    training_parser = subparsers.add_parser(
        "build-training",
        help="Freeze proxy gold, split by document and export GLiNER NER/Relex datasets",
    )
    training_parser.add_argument(
        "--reviewed",
        default=str(PROJECT_ROOT / "artifacts" / "pilot" / "pilot_seed_ai_reviewed.jsonl"),
    )
    training_parser.add_argument(
        "--expanded",
        default=str(PROJECT_ROOT / "artifacts" / "pilot" / "pilot_expanded_silver.jsonl"),
    )
    training_parser.add_argument("--output", default=str(PROJECT_ROOT / "artifacts"))
    training_parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    training_parser.add_argument("--version", default="0.2")
    training_parser.add_argument("--train-ratio", type=float, default=0.80)
    training_parser.add_argument("--dev-ratio", type=float, default=0.10)
    training_parser.add_argument("--test-ratio", type=float, default=0.10)
    training_parser.add_argument("--seed", type=int, default=42)
    training_parser.set_defaults(handler=build_training)

    simple_training_parser = subparsers.add_parser(
        "build-simple-training",
        help="Create complex-to-simple labels and sentence-level joint datasets",
    )
    simple_training_parser.add_argument(
        "--input",
        default=str(PROJECT_ROOT / "artifacts" / "gold" / "splits"),
        help="Directory containing train/dev/test JSONL section-level proxy gold",
    )
    simple_training_parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "artifacts" / "simple_joint_v1.3"),
    )
    simple_training_parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    simple_training_parser.add_argument("--version", default="1.3")
    simple_training_parser.add_argument("--minimum-relations", type=int, default=300)
    simple_training_parser.add_argument("--seed", type=int, default=42)
    simple_training_parser.set_defaults(handler=build_simple_training)

    inference_parser = subparsers.add_parser(
        "infer",
        help="Run the local joint model and export document-level entities/S-P-O",
    )
    inference_parser.add_argument(
        "--documents",
        default=str(PROJECT_ROOT / "artifacts" / "processed" / "documents.jsonl"),
        help="Processed, de-identified and deduplicated document JSONL",
    )
    inference_parser.add_argument(
        "--models-root",
        default=str(PROJECT_ROOT / "models"),
    )
    inference_parser.add_argument(
        "--model-run",
        help="Joint RelEx run directory; auto-detected from --models-root when omitted",
    )
    inference_parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "artifacts" / "inference" / "clinical_ie_spo.jsonl"),
    )
    inference_parser.add_argument(
        "--report",
        default=str(PROJECT_ROOT / "artifacts" / "reports" / "inference_report.json"),
    )
    inference_parser.add_argument(
        "--device",
        choices=("auto", "cpu", "mps", "cuda"),
        default="cpu",
    )
    inference_parser.add_argument("--batch-size", type=int, default=4)
    inference_parser.add_argument(
        "--document-batch-size",
        type=int,
        default=16,
        help="Number of documents prepared in one model.inference call",
    )
    inference_parser.add_argument(
        "--limit",
        type=int,
        help="Process only this many new documents (useful for smoke tests/chunks)",
    )
    inference_parser.add_argument(
        "--resume",
        action="store_true",
        help="Append while skipping doc_id values already present in --output",
    )
    inference_parser.add_argument(
        "--include-text",
        action="store_true",
        help="Include full medical-record text in output; off by default for privacy/size",
    )
    inference_parser.add_argument("--progress-every", type=int, default=25)
    inference_parser.add_argument("--shard-count", type=int, default=1)
    inference_parser.add_argument("--shard-index", type=int, default=0)
    inference_parser.set_defaults(handler=infer)

    inference_audit_parser = subparsers.add_parser(
        "audit-inference",
        help="Validate document coverage, offsets and S-P-O references",
    )
    inference_audit_parser.add_argument(
        "--documents",
        default=str(PROJECT_ROOT / "artifacts" / "processed" / "documents.jsonl"),
    )
    inference_audit_parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "artifacts" / "inference" / "clinical_ie_spo.jsonl"),
    )
    inference_audit_parser.add_argument(
        "--report",
        default=str(PROJECT_ROOT / "artifacts" / "reports" / "inference_audit.json"),
    )
    inference_audit_parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Do not fail only because not all source documents are present",
    )
    inference_audit_parser.set_defaults(handler=audit_inference)

    merge_parser = subparsers.add_parser(
        "merge-inference",
        help="Merge independent inference shard JSONL files safely",
    )
    merge_parser.add_argument("inputs", nargs="+")
    merge_parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "artifacts" / "inference" / "clinical_ie_spo.jsonl"),
    )
    merge_parser.add_argument(
        "--report",
        default=str(PROJECT_ROOT / "artifacts" / "reports" / "inference_merge.json"),
    )
    merge_parser.set_defaults(handler=merge_inference)

    demo_parser = subparsers.add_parser(
        "demo",
        help="Run one synthetic/text/file example and print readable entities/S-P-O",
    )
    demo_input = demo_parser.add_mutually_exclusive_group()
    demo_input.add_argument("--text", help="Clinical text supplied directly")
    demo_input.add_argument("--file", help="UTF-8 TXT file used for the demo")
    demo_parser.add_argument(
        "--section",
        default="auto",
        help="auto parses known section headers; otherwise force one section name",
    )
    demo_parser.add_argument(
        "--models-root",
        default=str(PROJECT_ROOT / "models"),
    )
    demo_parser.add_argument("--model-run")
    demo_parser.add_argument(
        "--device",
        choices=("auto", "cpu", "mps", "cuda"),
        default="cpu",
    )
    demo_parser.add_argument("--batch-size", type=int, default=4)
    demo_parser.add_argument(
        "--json-output",
        default=str(PROJECT_ROOT / "artifacts" / "demo" / "demo_output.json"),
    )
    demo_parser.set_defaults(handler=demo)

    status_parser = subparsers.add_parser(
        "simple-model-status",
        help="Validate downloaded simplifier and sentence-level joint model runs",
    )
    status_parser.add_argument("--models-root", default=str(PROJECT_ROOT / "models"))
    status_parser.add_argument("--simplifier-run")
    status_parser.add_argument("--joint-run")
    status_parser.set_defaults(handler=simple_model_status)

    simple_demo_parser = subparsers.add_parser(
        "simple-demo",
        help="Run complex-to-simple generation followed by sentence-level joint IE",
    )
    simple_demo_input = simple_demo_parser.add_mutually_exclusive_group()
    simple_demo_input.add_argument("--text", help="Clinical text supplied directly")
    simple_demo_input.add_argument("--file", help="UTF-8 TXT file used for the demo")
    simple_demo_parser.add_argument("--section", default="auto")
    simple_demo_parser.add_argument("--models-root", default=str(PROJECT_ROOT / "models"))
    simple_demo_parser.add_argument("--simplifier-run")
    simple_demo_parser.add_argument("--joint-run")
    simple_demo_parser.add_argument(
        "--device", choices=("auto", "cpu", "mps", "cuda"), default="auto"
    )
    simple_demo_parser.add_argument("--simplifier-batch-size", type=int, default=4)
    simple_demo_parser.add_argument("--joint-batch-size", type=int, default=8)
    simple_demo_parser.add_argument("--num-beams", type=int, default=4)
    simple_demo_parser.add_argument(
        "--json-output",
        default=str(PROJECT_ROOT / "artifacts" / "demo" / "simple_demo_output.json"),
    )
    simple_demo_parser.set_defaults(handler=simple_demo)

    simple_eval_parser = subparsers.add_parser(
        "evaluate-simple",
        help="Evaluate the full generated-simple-sentence pipeline on section test data",
    )
    simple_eval_parser.add_argument(
        "--test",
        default=str(
            PROJECT_ROOT
            / "artifacts"
            / "gold"
            / "v0.3"
            / "splits"
            / "test.jsonl"
        ),
    )
    simple_eval_parser.add_argument("--models-root", default=str(PROJECT_ROOT / "models"))
    simple_eval_parser.add_argument("--simplifier-run")
    simple_eval_parser.add_argument("--joint-run")
    simple_eval_parser.add_argument(
        "--device", choices=("auto", "cpu", "mps", "cuda"), default="auto"
    )
    simple_eval_parser.add_argument("--simplifier-batch-size", type=int, default=4)
    simple_eval_parser.add_argument("--joint-batch-size", type=int, default=8)
    simple_eval_parser.add_argument("--num-beams", type=int, default=4)
    simple_eval_parser.add_argument("--limit", type=int)
    simple_eval_parser.add_argument(
        "--predictions",
        default=str(
            PROJECT_ROOT / "artifacts" / "inference" / "simple_pipeline_test.jsonl"
        ),
    )
    simple_eval_parser.add_argument(
        "--report",
        default=str(
            PROJECT_ROOT / "artifacts" / "reports" / "simple_pipeline_evaluation.json"
        ),
    )
    simple_eval_parser.set_defaults(handler=evaluate_simple)
    from .graph import build_graphs_cli
    graph_parser = subparsers.add_parser("build-graphs", help="Export predictions as offline Neo4j property graphs")
    graph_parser.add_argument("--input", required=True, help="Prediction JSON or JSONL")
    graph_parser.add_argument("--output-dir", required=True)
    graph_parser.add_argument("--namespace", required=True, help="Snapshot name; use a new name for changed predictions")
    graph_parser.set_defaults(handler=build_graphs_cli)

    # ==========================================
    # Production Handover CLI Commands (P1-P3)
    # ==========================================
    doctor_p = subparsers.add_parser("doctor", help="Check local environment readiness and bundle integrity")
    doctor_p.add_argument("--ie-bundle", help="Path to clinical-ie-models bundle")
    doctor_p.add_argument("--classifier-bundle", help="Path to classifier-bundle")
    doctor_p.add_argument("--index-bundle", help="Path to reference-index bundle")
    doctor_p.set_defaults(handler=doctor_cli)

    analyze_p = subparsers.add_parser("analyze-file", help="Analyze clinical medical record TXT file")
    analyze_p.add_argument("--input", "-i", required=True, help="Path to clinical medical record TXT file")
    analyze_p.add_argument("--ie-bundle", required=True, help="Path to clinical-ie-models-v1.3 bundle")
    analyze_p.add_argument("--classifier-bundle", default=str(DEFAULT_CLASSIFIER_BUNDLE), help="Classifier bundle (default: dist/classifier-bundle-v2, Text+Graph)")
    analyze_p.add_argument("--image", help="Optional same-case X-ray; requires --classifier-bundle dist/classifier-fusion-v1")
    analyze_p.add_argument("--index-bundle", required=True, help="Path to reference index bundle (recommended: reference-index-v1.1)")
    analyze_p.add_argument("--document-id", help="Explicit document identifier")
    analyze_p.add_argument("--namespace", default="case", help="Case graph namespace")
    analyze_p.add_argument("--output", "-o", help="Destination JSON output path (prints to stdout if omitted)")
    analyze_p.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto")
    analyze_p.add_argument(
        "--allow-rule-fallback",
        action="store_true",
        default=False,
        help="Explicitly permit falling back to heuristic rule IE if neural model bundle is missing/invalid (default: False, fail-closed)",
    )
    analyze_p.set_defaults(handler=analyze_file_cli)

    symptoms_p = subparsers.add_parser("ask-symptoms", help="Single-turn Vietnamese symptom description question")
    symptoms_p.add_argument("--text", "-t", required=True, help="Symptom question text")
    symptoms_p.add_argument("--ie-bundle", required=True, help="Path to clinical-ie-models-v1.3 bundle")
    symptoms_p.add_argument("--classifier-bundle", default=str(DEFAULT_CLASSIFIER_BUNDLE), help="Classifier bundle (default: dist/classifier-bundle-v2, Text+Graph)")
    symptoms_p.add_argument("--image", help="Optional same-case X-ray; requires the late-fusion classifier bundle")
    symptoms_p.add_argument("--index-bundle", required=True, help="Path to reference index bundle (recommended: reference-index-v1.1)")
    symptoms_p.add_argument("--output", "-o", help="Destination JSON output path")
    symptoms_p.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto")
    symptoms_p.add_argument(
        "--allow-rule-fallback",
        action="store_true",
        default=False,
        help="Explicitly permit falling back to heuristic rule IE if neural model bundle is missing/invalid (default: False, fail-closed)",
    )
    symptoms_p.set_defaults(handler=ask_symptoms_cli)

    entity_p = subparsers.add_parser("analyze-entities", help="Type and classify an array of independent entity strings")
    entity_input = entity_p.add_mutually_exclusive_group(required=True)
    entity_input.add_argument("--entities", help='JSON string array, e.g. ["ho", "sốt"]')
    entity_input.add_argument("--input", help="UTF-8 JSON file containing a string array")
    entity_p.add_argument("--ie-bundle", required=True)
    entity_p.add_argument("--classifier-bundle", default=str(DEFAULT_CLASSIFIER_BUNDLE))
    entity_p.add_argument("--index-bundle", required=True)
    entity_p.add_argument("--image", help="Optional same-case image; requires a fusion bundle")
    entity_p.add_argument("--document-id")
    entity_p.add_argument("--namespace", default="entity_case")
    entity_p.add_argument("--output", "-o")
    entity_p.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto")
    entity_p.add_argument("--allow-rule-fallback", action="store_true", default=False)
    entity_p.set_defaults(handler=analyze_entities_cli)

    extract_p = subparsers.add_parser("extract", help="Extract entities, qualifiers and S-P-O triples")
    extract_inp = extract_p.add_mutually_exclusive_group(required=True)
    extract_inp.add_argument("--text", "-t", help="Text to extract")
    extract_inp.add_argument("--file", "-f", help="File to extract")
    extract_p.add_argument("--ie-bundle", help="Path to IE bundle")
    extract_p.add_argument("--output", "-o", help="Destination JSON output path")
    extract_p.add_argument("--device", choices=("auto", "cpu", "mps", "cuda"), default="auto")
    extract_p.set_defaults(handler=extract_cli)

    graph_p = subparsers.add_parser("graph", help="Build and deduplicate case graph from extraction JSON")
    graph_p.add_argument("--input", "-i", required=True, help="Extraction JSON file")
    graph_p.add_argument("--output", "-o", help="Destination JSON file")
    graph_p.add_argument("--namespace", default="case")
    graph_p.add_argument("--no-dedup", dest="dedup", action="store_false", default=True, help="Skip entity deduplication")
    graph_p.set_defaults(handler=graph_cli)

    return parser


def doctor_cli(args: argparse.Namespace) -> int:
    from .api import doctor
    report = doctor(
        ie_bundle=args.ie_bundle,
        classifier_bundle=args.classifier_bundle,
        index_bundle=args.index_bundle,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "PASS" else 1


def analyze_file_cli(args: argparse.Namespace) -> int:
    from .api import ResearchAssistant
    assistant = ResearchAssistant.from_bundles(
        ie_bundle=args.ie_bundle,
        classifier_bundle=args.classifier_bundle,
        index_bundle=args.index_bundle,
        device=args.device,
        allow_rule_fallback=args.allow_rule_fallback,
    )
    result = assistant.analyze_file(
        args.input,
        document_id=args.document_id,
        namespace=args.namespace or "case",
        image_path=args.image,
    )
    res_dict = result.to_dict()
    if args.output:
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(res_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Kết quả phân tích đã ghi tại: {out_p.resolve()}")
    else:
        print(json.dumps(res_dict, ensure_ascii=False, indent=2))
    return 0


def ask_symptoms_cli(args: argparse.Namespace) -> int:
    from .api import ResearchAssistant
    assistant = ResearchAssistant.from_bundles(
        ie_bundle=args.ie_bundle,
        classifier_bundle=args.classifier_bundle,
        index_bundle=args.index_bundle,
        device=args.device,
        allow_rule_fallback=args.allow_rule_fallback,
    )
    answer = assistant.ask_symptoms(args.text, image_path=args.image)
    ans_dict = answer.to_dict()
    if args.output:
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(ans_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Kết quả truy vấn triệu chứng đã ghi tại: {out_p.resolve()}")
    else:
        print(json.dumps(ans_dict, ensure_ascii=False, indent=2))
    return 0


def analyze_entities_cli(args: argparse.Namespace) -> int:
    from .api import ResearchAssistant
    raw = Path(args.input).read_text(encoding="utf-8") if args.input else args.entities
    entities = json.loads(raw)
    # Validate before allocating neural models.
    if not isinstance(entities, list) or any(not isinstance(v, str) or not v.strip() for v in entities):
        raise ValueError("entities must be a JSON array of non-empty strings")
    assistant = ResearchAssistant.from_bundles(
        args.ie_bundle, args.classifier_bundle, args.index_bundle,
        device=args.device, allow_rule_fallback=args.allow_rule_fallback)
    result = assistant.analyze_entities(entities, document_id=args.document_id,
                                        namespace=args.namespace, image_path=args.image)
    if args.output:
        _atomic_write_json(Path(args.output), result.to_dict())
        print(f"Kết quả entity đã ghi tại: {Path(args.output).resolve()}")
    else:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def extract_cli(args: argparse.Namespace) -> int:
    from .api import ClinicalPipeline
    if args.ie_bundle:
        pipeline = ClinicalPipeline.from_bundle(args.ie_bundle, device=args.device)
    else:
        pipeline = ClinicalPipeline(device=args.device)

    if args.file:
        res = pipeline.extract_file(args.file)
    elif args.text:
        res = pipeline.extract_text(args.text)
    else:
        raise SystemExit("Cần cung cấp --text hoặc --file.")

    res_dict = res.to_dict()
    if args.output:
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(res_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Kết quả trích xuất đã ghi tại: {out_p.resolve()}")
    else:
        print(json.dumps(res_dict, ensure_ascii=False, indent=2))
    return 0


def graph_cli(args: argparse.Namespace) -> int:
    from .graph import build_case_graph, deduplicate_case_graph
    in_p = Path(args.input)
    if not in_p.is_file():
        raise SystemExit(f"Không tìm thấy file: {in_p}")
    data = json.loads(in_p.read_text(encoding="utf-8"))
    raw_graph = build_case_graph(data, namespace=args.namespace or "case")
    if args.dedup:
        final_graph = deduplicate_case_graph(raw_graph, namespace=f"{args.namespace or 'case'}_dedup")
    else:
        final_graph = raw_graph

    if args.output:
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(final_graph, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Đồ thị đã lưu tại: {out_p.resolve()}")
    else:
        print(json.dumps(final_graph, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help()
        return 0
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
