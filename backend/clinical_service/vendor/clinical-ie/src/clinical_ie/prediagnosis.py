"""Conservative, auditable pre-diagnosis *candidate* data preparation.

No clinical timestamp certification, model inference or classifier training.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from .preprocess import canonical_content

VERSION = "prediagnosis_candidate_v1"
LABELS = ("Binhthuong", "COPD", "Covid", "Hen", "Lao", "Phuphoi", "Suyhohap", "Trandich", "Trankhi", "Uphoi", "Viemphoi", "Xepphoi")
ALLOWED = {"hoibenh_quatrinhbenhly", "khambenh_toanthan", "caccoquan_hohap", "caccoquan_tuanhoan", "tiensubenh_banthan"}
PATTERNS = {
    "target_disease_mention": r"\b(?:viêm\s*(?:phổi|phế\s*quản\s*phổi)|vp|covid[ -]?(?:19)?|sars[ -]?(?:cov[ -]?2|covi[ -]?2)|copd|bptnmt|bệnh\s*phổi\s*tắc\s*nghẽn|suy\s*hô\s*hấp|shh|lao|tràn\s*(?:dịch|khí)|tdmp|tkmp|hen|suyễn|phù\s*phổi|oap|(?:u|ung\s*thư|k)\s*(?:phổi|phế\s*quản)|xẹp\s*phổi)\b",
    "explicit_diagnosis": r"\b(?:chẩn\s*đoán|chẩn\s*đ[oó]an|ch[aẩ]n\s*đoán|cđ|diagnos\w*|kết\s*luận|xác\s*định\s*bệnh)\b|\b(?:J\d{2}|U0[67])(?:\.\d+)?\b",
    "treatment_or_response": r"\b(?:điều\s*trị|đtrị|đt|kháng\s*sinh|thuốc|truyền\s*dịch|lọc\s*máu|dẫn\s*lưu|phẫu\s*thuật|sau\s*mổ|thở\s*(?:oxy|oxi|ô\s*xy|máy|cpap)|(?:oxy|oxi|mask|ncpap|cpap|bipap)|nội\s*khí\s*quản|đặt\s*nkq|xuất\s*viện|ra\s*viện|hết\s*(?:sốt|ho|khó\s*thở)|cải\s*thiện|đáp\s*ứng)\b",
    "investigation_time_unknown": r"\b(?:x[ -]?quang|ct[ -]?scan|ct\s*(?:ngực|phổi)|pcr|rt[ -]?pcr|test\s*nhanh|xét\s*nghiệm|siêu\s*âm|chụp\s*phim|dương\s*tính|âm\s*tính)\b",
    "diagnosis_spelling_or_abbreviation": r"\b(?:chuẩn\s*đoán|chấn\s*đoán|viêm\s*phôi|hpq|ppc|vpqp|di\s*căn\s*(?:phổi|màng\s*phổi)|k\s*(?:màng\s*phổi|phê\s*quản))\b",
    "intervention_abbreviation": r"\b(?:đều\s*trị|nkq|hfnc|ecmo|fio2|peep|bóp\s*bóng|sonde|xạ\s*trị|hóa\s*trị|hoá\s*trị)\b",
    "contact_metadata": r"\[(?:PHONE|EMAIL|PATIENT_ID)\]|\b(?:sđt|số\s*điện\s*thoại|họ\s*tên|địa\s*chỉ)\b",
}
# A newline is a clinical unit boundary: "không phù\nPhổi..." is not "phù phổi".
RULES = {key: re.compile(pattern.replace(r"\s", r"[^\S\n]"), re.I) for key, pattern in PATTERNS.items()}
# Keep numbers, negation and wording intact; do not split on commas or slashes.
BOUNDARY = re.compile(r"\n+|[;!?]+|(?<!\d)\.(?=\s|$)|\.(?!\d)(?=\s+[A-ZÀ-Ỹ])")


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def read_rows(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def units(text):
    start = 0
    for match in BOUNDARY.finditer(text):
        end = match.end()
        if text[start:end].strip():
            yield start, end, text[start:end].strip()
        start = end
    if text[start:].strip():
        yield start, len(text), text[start:].strip()


def clean_document(doc):
    """Label independent. Return source-preserving candidate + decision ledger."""
    sections, decisions = [], []
    cursor = 0
    for section_index, section in enumerate(doc["sections"]):
        source = section["text"]
        spans = list(units(source)) if section["name"] in ALLOWED else [(0, len(source), source)]
        kept = []
        for start, end, text in spans:
            reasons = [key for key, rule in RULES.items() if rule.search(text)]
            if section["name"] not in ALLOWED:
                reasons.insert(0, "excluded_section_retrospective_or_unknown")
            decision = {"doc_id": doc["doc_id"], "section_index": section_index, "section": section["name"],
                        "source_start": start, "source_end": end, "action": "drop" if reasons else "keep", "reasons": reasons}
            decisions.append(decision)
            if not reasons:
                kept.append(text)
        if kept:
            text = "\n".join(kept)
            if sections:
                cursor += 1
            sections.append({"name": section["name"], "text": text, "doc_start": cursor, "doc_end": cursor + len(text)})
            cursor += len(text)
    text = "\n".join(s["text"] for s in sections)
    candidate = {"doc_id": doc["doc_id"], "content_hash": digest(canonical_content(text)), "text": text,
                 "sections": sections, "disease_labels": [], "data_policy": VERSION,
                 "temporal_status": "section_proxy_not_timestamp_verified"}
    return candidate, decisions


def template_text(text):
    # Group numerical variants only for splitting; never overwrite clinical values.
    text = canonical_content(text)
    text = re.sub(r"\d+(?:[.,]\d+)*", "<num>", text)
    return re.sub(r"[^\w<>]+", " ", text).strip()


def shingles(text):
    words = text.split()
    if len(words) < 4:
        return {text}
    return {" ".join(words[i:i+4]) for i in range(len(words)-3)}


class UnionFind:
    def __init__(self, size):
        self.parent = list(range(size))

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        self.parent[max(a, b)] = min(a, b)


def similarity_groups(documents):
    """Exact/template grouping + approximate MinHash candidates with exact check."""
    import numpy as np
    uf = UnionFind(len(documents))
    buckets = defaultdict(list)
    exact, templates = {}, {}
    signatures, sets = [], []
    # Fixed universal hash coefficients, stable across Python processes.
    rng = random.Random(17)
    a = np.array([rng.randrange(1, 2**31-1) for _ in range(64)], dtype=np.uint64)
    b = np.array([rng.randrange(0, 2**31-1) for _ in range(64)], dtype=np.uint64)
    pairs, template_links = [], 0
    for i, doc in enumerate(documents):
        text = template_text(doc["text"])
        key = digest(text)
        if key in templates:
            uf.union(i, templates[key]); template_links += 1
        else:
            templates[key] = i
        h = doc["content_hash"]
        if h in exact:
            uf.union(i, exact[h])
        else:
            exact[h] = i
        ss = shingles(text)
        sets.append(ss)
        vals = np.array([int.from_bytes(hashlib.blake2b(s.encode(), digest_size=4).digest(), "big") % (2**31-1) for s in ss], dtype=np.uint64)
        signature = ((vals[:, None]*a+b) % np.uint64(2**31-1)).min(axis=0)
        signatures.append(signature)
        for band in range(16):
            buckets[(band, tuple(map(int, signature[band*4:band*4+4])))].append(i)
    candidates = set()
    for members in buckets.values():
        # Same template is already grouped. Compare representatives only.
        members = sorted({templates[digest(template_text(documents[i]["text"]))] for i in members})
        for pos, i in enumerate(members):
            for j in members[pos+1:]:
                if min(len(sets[i]), len(sets[j])) / max(len(sets[i]), len(sets[j])) >= .9:
                    candidates.add((i,j))
    for i, j in sorted(candidates):
        score = len(sets[i] & sets[j]) / len(sets[i] | sets[j])
        if score >= .9:
            uf.union(i,j)
            pairs.append({"a": documents[i]["doc_id"], "b": documents[j]["doc_id"], "jaccard": round(score, 6)})
    groups = defaultdict(list)
    for i, doc in enumerate(documents):
        groups[uf.find(i)].append(doc["doc_id"])
    return list(groups.values()), pairs, {"candidate_pairs_checked": len(candidates), "near_pairs": len(pairs), "template_links": template_links,
                                        "near_duplicate_method": "64-hash/16-band MinHash candidate search, word-4gram Jaccard >=0.90 on number-masked text; approximate, not exhaustive"}


def exposure_inventory(root):
    """Conservatively include all locally available IE development split versions."""
    files = sorted((root / "artifacts").glob("**/splits/*.jsonl"))
    files = [p for p in files if "classification" not in p.parts]
    seen, manifest = set(), []
    for path in files:
        rows = read_rows(path)
        ids = {r["doc_id"] for r in rows if r.get("doc_id")}
        seen.update(ids)
        manifest.append({"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "documents": len(ids)})
    # Original TXT aliases in exact dedup groups may have been used for IE.
    for group in read_rows(root / "artifacts/processed/dedup_groups.jsonl"):
        if seen.intersection(group["doc_ids"]):
            seen.update(group["doc_ids"])
    return seen, manifest


def prepare(root, output):
    from .cli import _atomic_write_json, _atomic_write_jsonl
    source = root / "artifacts/processed/documents.jsonl"
    originals = read_rows(source)
    seen, exposure_sources = exposure_inventory(root)
    labels = {d["doc_id"]: d["disease_labels"] for d in originals}
    if any(len(ls)!=1 or ls[0] not in LABELS for ls in labels.values()):
        raise ValueError("Expected exactly one of 12 source labels per document; no implicit relabeling")
    candidates, decisions, excluded = [], [], []
    original_by_id = {d["doc_id"]:d for d in originals}
    for original in originals:
        candidate, ledger = clean_document(original)
        decisions.extend(ledger)
        if len(re.findall(r"\w+", candidate["text"])) < 5:
            excluded.append({"doc_id":candidate["doc_id"],"reason":"fewer_than_5_retained_tokens"})
        else:
            candidates.append(candidate)
    candidates.sort(key=lambda d:d["doc_id"])
    by_hash = defaultdict(list)
    for doc in candidates:
        by_hash[doc["content_hash"]].append(doc)
    conflicts, duplicates = [], []
    # Equal censored features do NOT prove duplicate patients or incorrect labels.
    # Retain all cases, group for splitting, and report ambiguity without adjudication.
    representatives = candidates
    for h, members in sorted(by_hash.items()):
        source_labels = sorted({labels[m["doc_id"]][0] for m in members})
        if len(source_labels)>1:
            conflicts.append({"content_hash":h,"doc_ids":[d["doc_id"] for d in members],"labels":source_labels})
        if len(members)>1:
            duplicates.append({"content_hash":h,"members":[d["doc_id"] for d in members],"action":"retain_and_group_not_delete"})
    groups, near_pairs, similarity_report = similarity_groups(representatives)
    docs_by_id={d["doc_id"]:d for d in representatives}
    # Also group on the *unfiltered* template: cleaning should not split known siblings.
    uf=UnionFind(len(groups));group_index={doc:i for i,g in enumerate(groups) for doc in g}
    original_templates={}
    for doc in representatives:
        key=digest(template_text(original_by_id[doc["doc_id"]]["text"]))
        if key in original_templates:
            uf.union(group_index[doc["doc_id"]],group_index[original_templates[key]])
        else:original_templates[key]=doc["doc_id"]
    combined=defaultdict(list)
    for i,g in enumerate(groups):combined[uf.find(i)].extend(g)
    groups=[sorted(g) for g in combined.values()]
    grouping=[];holdout=[];forced=[]
    for members in groups:
        exposed=any(d in seen for d in members)
        row={"group_id":"GRP_"+digest("|".join(members))[:16],"doc_ids":members,"upstream_development_exposed":exposed}
        grouping.append(row)
        (forced if exposed else holdout).extend(members)
    availability=Counter(labels[d][0] for d in holdout)
    counts=Counter(labels[d["doc_id"]][0] for d in representatives)
    source_counts=Counter(labels[d["doc_id"]][0] for d in originals)
    reason_counts=Counter(r for item in decisions for r in item["reasons"])
    kept_counts=Counter(x["section"] for x in decisions if x["action"]=="keep")
    retained_audit = []
    for doc in representatives:
        original=original_by_id[doc['doc_id']]
        flags=[]
        if not any(s['name']=='hoibenh_quatrinhbenhly' for s in doc['sections']):flags.append('no_retained_present_illness')
        if any(RULES['treatment_or_response'].search(s['text']) or RULES['intervention_abbreviation'].search(s['text']) for s in original['sections'] if s['name'] in {'khambenh_toanthan','caccoquan_hohap','caccoquan_tuanhoan'}):flags.append('exam_has_intervention_context_remaining_measurements_not_proven_untreated')
        if re.search(r'vacci\w*|vắc.?xin|tiêm\s*ngừa|verocell|pfizer',doc['text'],re.I):flags.append('vaccination_history_possible_source_shortcut_not_confirmed_leakage')
        if re.search(r'kho7ng|kho6ng|khong',doc['text'],re.I):flags.append('possible_negation_typo_not_auto_corrected')
        if re.search(r'\b(?:thở|khó thở) co kéo',doc['text'],re.I) and re.search(r'\bkhông co kéo',doc['text'],re.I):flags.append('opposing_retraction_statements_timing_unknown')
        if flags:retained_audit.append({'doc_id':doc['doc_id'],'flags':flags})
    report={"version":VERSION,"status":"CANDIDATE_ONLY_NOT_TEMPORALLY_CERTIFIED","source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
            "source_documents":len(originals),"candidate_documents":len(representatives),"unique_filtered_texts":len(by_hash),
            "excluded_documents":len(excluded),"filtered_exact_duplicates_removed":0,"filtered_equal_input_groups":len(duplicates),
            "filtered_input_label_conflict_groups":len(conflicts),"filtered_input_label_conflict_documents":sum(len(g["doc_ids"]) for g in conflicts),
            "dropped_units":sum(x["action"]=="drop" for x in decisions),"kept_units":sum(x["action"]=="keep" for x in decisions),
            "drop_reason_counts":dict(reason_counts),"retained_units_by_section":dict(kept_counts),"similarity":similarity_report,
            "quality_flags":dict(Counter(flag for row in retained_audit for flag in row['flags'])),
            "split_groups":len(groups),"largest_group":max(map(len,groups),default=0),"upstream_exposed_candidates":len(forced),
            "unexposed_holdout_pool":len(holdout),"per_class":[{"label":label,"source":source_counts[label],"candidate":counts[label],"unexposed":availability[label]} for label in LABELS],
            "insufficient_unexposed_classes_under_20":[label for label in LABELS if availability[label]<20],
            "split_status":"NOT_FROZEN: holdout feasibility and prediction-time policy require discussion",
            "limitations":["No reliable patient ID or per-event diagnostic timestamp: patient-disjoint and truly prediagnostic status cannot be certified.",
                           "Section-based filtering and regexes are conservative proxies; implicit diagnosis, spelling errors and unmarked treatment may remain. Retained measurements are not certified pre-treatment.",
                           "All target disease names are screened independent of the true label, including history; this discards potentially valid prediagnostic evidence.",
                           "Normal examination phrases are retained; Binhthuong is a source class name, not verified absence of all disease.",
                           "Conflicts refer to identical FILTERED inputs with different source labels; retained and grouped, not removed to make evaluation artificially easier.",
                           "Near-duplicate search is approximate. Local development exposure inventory is not proof of complete model training provenance."]}
    policy={"version":VERSION,"allowed_sections":sorted(ALLOWED),"exclude_all_other_sections":True,"drop_unit_regexes":PATTERNS,
            "regex_whitespace":"Horizontal whitespace only, never cross newline to infer a disease phrase",
            "label_independent":True,"preserve_negation_numbers_original_wording":True,"min_retained_tokens":5,
            "clinical_cutoff":"before final diagnosis; approximated by non-diagnostic history/intake exam only",
            "missing_is_not_negated":True,"target_labels_are_separate":True}
    # Validate before writing output files.
    assert len({d['doc_id'] for d in representatives})==len(representatives)
    assert set(forced).isdisjoint(holdout)
    assert set(forced)|set(holdout)==set(docs_by_id)
    for doc in representatives:
        assert not doc["disease_labels"]
        assert not any(rule.search(doc["text"]) for rule in RULES.values())
        for s in doc["sections"]:
            assert doc["text"][s["doc_start"]:s["doc_end"]]==s["text"]
    # Evidence linkage stays outside the classifier input.
    output.mkdir(parents=True,exist_ok=True)
    _atomic_write_jsonl(output/"documents.jsonl",sorted(representatives,key=lambda d:d["doc_id"]))
    _atomic_write_jsonl(output/"targets.jsonl",({"doc_id":d["doc_id"],"label":labels[d["doc_id"]][0],"class_id":LABELS.index(labels[d["doc_id"]][0])} for d in representatives))
    for name,rows in [("decisions",decisions),("excluded",excluded),("quality_flags",retained_audit),("duplicate_groups",duplicates),("filtered_label_conflicts",conflicts),("split_groups",grouping),("near_duplicate_pairs",near_pairs),
                      ("holdout_candidates",[{"doc_id":d} for d in sorted(holdout)]),("train_only_candidates",[{"doc_id":d} for d in sorted(forced)])]:
        _atomic_write_jsonl(output/(name+".jsonl"),rows)
    _atomic_write_json(output/"policy.json",policy)
    _atomic_write_json(output/"upstream_exposure_sources.json",exposure_sources)
    _atomic_write_json(output/"report.json",report)
    # Fixed, stratified review sample with source snippets kept locally.
    rng=random.Random(17);samples=[]
    for label in LABELS:
        pool=[d for d in representatives if labels[d["doc_id"]]==[label]]
        for d in rng.sample(pool,min(4,len(pool))):
            audit=[x for x in decisions if x["doc_id"]==d["doc_id"]]
            source_doc=original_by_id[d["doc_id"]]
            samples.append({"doc_id":d["doc_id"],"label":label,"retained_text":d["text"],
                            "removed":[{"reason":a["reasons"],"text":source_doc["sections"][a["section_index"]]["text"][a["source_start"]:a["source_end"]]} for a in audit if a["action"]=="drop"]})
    _atomic_write_jsonl(output/"review_sample.jsonl",samples)
    _atomic_write_json(output/"checksums.json",{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.glob('*.json*')) if p.name not in {'checksums.json','manual_review.json'}})
    return report
