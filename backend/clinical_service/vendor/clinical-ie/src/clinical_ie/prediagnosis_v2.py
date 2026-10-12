"""Verbatim context-aware recovery and exposure-aware exploratory partitions."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from .cli import _atomic_write_json, _atomic_write_jsonl
from .prediagnosis import (
    ALLOWED, LABELS, RULES, UnionFind, digest, exposure_inventory, read_rows,
    similarity_groups, template_text, units,
)
from .preprocess import canonical_content
from .training import sha256_file

VERSION = "prediagnosis_context_v2"
SEED = 20260917
HISTORY = re.compile(r"\b(?:tiền\s*(?:sử|căn)|từ\s*(?:nhỏ|bé)|cách\s*\d+\s*năm|\d+\s*năm\s*trước|(?:phổi|hen|copd)\s*cũ)\b", re.I)
CURRENT = re.compile(r"\b(?:đang|hiện\s*tại|vừa|mới|lần\s*này|đợt\s*này|theo\s*dõi|nghi\s*ngờ|dương\s*tính)\b|\?", re.I)
RESET = re.compile(r",\s*(?=(?:nay|hiện tại|lần này|đợt này|cùng ngày|bệnh nhân)\b)", re.I)
SUPPORT = re.compile(r"\b(?:oxy|oxi|mask|n?cpap|bipap|nkq|hfnc|ecmo|fio2|peep|bóp\s*bóng|thở\s*máy)\b", re.I)
CLINICAL = re.compile(r"\b(?:ho|sốt|khó\s*thở|khò\s*khè|mệt|đau|nôn|ói|đàm|chảy|tiêu|bú|ăn|tỉnh|co\s*kéo|sp[o0]2|nhiệt\s*độ|mạch|tim|phổi|da|niêm|huyết\s*áp|chi|rung\s*thanh|rale|ran|thở|phù|xuất\s*huyết|lơ\s*mơ|chóng\s*mặt)\b", re.I)
CONNECTOR = re.compile(r"(?:\s|,)(?:(?:không|chưa|có|đã|đang|được|tự|nay|và|nhưng|rồi|sau\s*đó|với|do|vì|nên|theo\s*dõi|nghi\s*ngờ|uống|dùng|tiêm|vào|xin|đi|chích|mua|kèm|qua|người\s*nhà|cho)\s*)+$", re.I)
MEASUREMENT = re.compile(r"\b(?:sp[o0]2|sa[o0]2|huyết\s*áp|nhịp\s*thở|nhiệt\s*độ|mạch)\b|\d+\s*%", re.I)
EXTRA_TREATMENT = re.compile(r"\b(?:chích\s*tư|khí\s*dung|phun\s*\d+\s*liều)\b", re.I)


def context_units(text):
    """A semicolon list shares its heading/negation, so never detach its items."""
    pending = None
    for start, end, value in units(text):
        start = pending if pending is not None else start
        if value.endswith(';'):
            pending = start
        else:
            yield start, end, text[start:end].strip()
            pending = None
    if pending is not None:
        yield pending, len(text), text[pending:].strip()


def rule_hits(text):
    hits=[]
    for key,rule in RULES.items():
        for m in rule.finditer(text):
            if key=='treatment_or_response':
                if m.group().casefold()=='thuốc' and (re.search(r'hút\s*$',text[:m.start()],re.I) or re.match(r'\s*(?:lá|lào)\b',text[m.end():],re.I)):
                    continue  # Smoking is an exposure, not medication administration.
                if m.group().casefold()=='đáp ứng' and re.search(r'(?:kích thích|cấu véo|đau|gọi)\b[^.;\n]{0,25}$',text[:m.start()],re.I):
                    continue  # Neurological examination response, not treatment response.
            hits.append((m.start(),key))
    hits.extend((m.start(), 'treatment_or_response') for m in EXTRA_TREATMENT.finditer(text))
    return hits


def trim_span(text, start, end, cut=False):
    while start < end and text[start].isspace():
        start += 1
    suffix = " \t\r\n,;:+-=><" if cut else " \t\r\n"
    while end > start and text[end-1] in suffix:
        end -= 1
    return start, end


def explicit_history(text):
    """Section title alone is never historical evidence for a target disease."""
    if CURRENT.search(text):
        return False
    diseases = list(RULES["target_disease_mention"].finditer(text))
    if not diseases:
        return False
    if re.match(r"\s*[-+]*\s*(?:tiền\s*sử|tiền\s*căn)\b", text, re.I):
        return True
    # A local old-disease cue cannot confer history on another list item.
    for disease in diseases:
        a = text.rfind(",", 0, disease.start()) + 1
        b = text.find(",", disease.end())
        if not HISTORY.search(text[a:b if b >= 0 else len(text)]):
            return False
    return True


def choose_span(text):
    """Return prefix bounds and reason. Never retain a suffix after an unsafe event."""
    hits = rule_hits(text)
    if not hits:
        return (0, len(text)), "unchanged_safe_unit"
    reasons = {key for _, key in hits}
    # A support context modifies the measurement even if separated by a comma.
    if SUPPORT.search(text):
        return None, "support_context_kept_together_but_withheld"
    if explicit_history(text) and not reasons.intersection({"contact_metadata", "investigation_time_unknown", "diagnosis_spelling_or_abbreviation"}):
        return (0, len(text)), "explicit_history_verbatim"
    cut = min(pos for pos, _ in hits)
    # Do not emit an unfinished parenthesis if the excluded text completes it.
    opens=[]
    for i, char in enumerate(text[:cut]):
        if char == '(':
            opens.append(i)
        elif char == ')' and opens:
            opens.pop()
    if opens:
        cut = opens[0]
    prefix = text[:cut]
    # Remove only trailing connective material, never rewrite symptoms/negations.
    connector = CONNECTOR.search(prefix)
    if connector:
        cut = connector.start()
    start, cut = trim_span(text, 0, cut, cut=True)
    prefix = text[start:cut]
    if CLINICAL.search(prefix) and len(re.findall(r"\w+", prefix)) >= 2:
        return (start, cut), "safe_prefix_before_diagnostic_or_treatment_clause"
    return None, "unsafe_or_context_insufficient"


def recover_document(original):
    sections, provenance, decisions = [], [], []
    cursor = 0
    for section_index, section in enumerate(original["sections"]):
        source = section["text"]
        selected=[]
        support_in_exam = section['name'] in {'khambenh_toanthan','caccoquan_hohap','caccoquan_tuanhoan'} and SUPPORT.search(source)
        source_units = list(context_units(source)) if section["name"] in ALLOWED else [(0, len(source), source)]
        for unit_start, unit_end, _ in source_units:
            base_start, base_end = trim_span(source, unit_start, unit_end)
            # Explicit current-time resets separate history from current symptoms.
            cuts = [base_start] + [base_start + m.end() for m in RESET.finditer(source[base_start:base_end])] + [base_end]
            for a, b in zip(cuts, cuts[1:]):
                a,b = trim_span(source,a,b)
                text = source[a:b]
                if SUPPORT.search(source[base_start:base_end]) or (support_in_exam and MEASUREMENT.search(text)):
                    span,reason=None,'measurement_support_context_withheld_together'
                elif section["name"] in ALLOWED:
                    span, reason = choose_span(text)
                else:
                    span, reason = None, "excluded_retrospective_section"
                decision = {"doc_id":original["doc_id"],"source_section_index":section_index,
                            "unit_start":a,"unit_end":b,"reason":reason,"action":"keep" if span else "withhold"}
                if span:
                    lo, hi = a+span[0], a+span[1]
                    selected.append((lo,hi,reason))
                    decision.update(kept_start=lo,kept_end=hi)
                decisions.append(decision)
        # Keep adjacent unaffected units together, including their original
        # punctuation/whitespace, to preserve e.g. negation over a semicolon list.
        merged=[]
        for lo,hi,reason in selected:
            if merged and reason==merged[-1][2]=='unchanged_safe_unit' and not source[merged[-1][1]:lo].strip():
                merged[-1]=(merged[-1][0],hi,reason)
            else:merged.append((lo,hi,reason))
        for lo,hi,reason in merged:
            value=source[lo:hi]
            if sections:cursor+=1
            out_index=len(sections)
            sections.append({'name':section['name'],'text':value,'doc_start':cursor,'doc_end':cursor+len(value)})
            provenance.append({'doc_id':original['doc_id'],'output_section_index':out_index,
                               'output_start':cursor,'output_end':cursor+len(value),
                               'source_section_index':section_index,'source_start':lo,'source_end':hi,
                               'source_slice_sha256':digest(value),'decision':reason})
            cursor+=len(value)
    text = "\n".join(s["text"] for s in sections)
    return {"doc_id":original["doc_id"],"text":text,"sections":sections,"disease_labels":[],
            "content_hash":digest(canonical_content(text)),"data_policy":VERSION,
            "temporal_status":"retrospective_proxy_not_timestamp_verified"}, provenance, decisions


def make_partitions(groups, labels, seed=SEED):
    """Greedy group-stratified 70/15/15 targets with scarce-holdout caps.

    Entire development-exposed groups are train-only. A rare class's limited
    unseen pool is split as evenly as possible, with test receiving the odd case.
    """
    counts = Counter(labels[d] for g in groups for d in g["doc_ids"])
    unseen = Counter(labels[d] for g in groups if not g["upstream_development_exposed"] for d in g["doc_ids"])
    wanted = {"validation":{},"test":{}}
    for label in LABELS:
        target = max(1, round(counts[label]*.15)) if counts[label] else 0
        wanted['validation'][label] = min(target, unseen[label]//2)
        wanted['test'][label] = min(target, unseen[label]-wanted['validation'][label])
    totals = {split:Counter() for split in ('train','validation','test')}
    assignments = {}
    available=[]
    for group in groups:
        if group['upstream_development_exposed']:
            assignments[group['group_id']]='train'
            totals['train'].update(labels[d] for d in group['doc_ids'])
        else:
            available.append(group)
    features={g['group_id']:Counter(labels[d] for d in g['doc_ids']) for g in available}
    # Rare classes first, and smaller groups first to avoid needless overshoot.
    available.sort(key=lambda g:(min(unseen[c] for c in features[g['group_id']]),len(g['doc_ids']),digest(str(seed)+g['group_id'])))
    for group in available:
        size=features[group['group_id']]
        scores={}
        for split in ('test','validation'):
            benefit=sum(min(n,max(0,wanted[split][c]-totals[split][c]))/max(1,wanted[split][c]) for c,n in size.items())
            penalty=sum(max(0,totals[split][c]+n-wanted[split][c])/max(1,wanted[split][c]) for c,n in size.items())
            scores[split]=benefit-.5*penalty
        winner=max(scores,key=scores.get)
        if scores[winner] <= 0:
            winner='train'
        assignments[group['group_id']]=winner
        totals[winner].update(size)
    return assignments, wanted, totals


def build(root: Path, output: Path):
    source=root/'artifacts/processed/documents.jsonl'
    strict=root/'artifacts/classification/prediagnosis_v1'
    destination=output.resolve()
    for protected in (source.parent.resolve(), strict.resolve(), (root/'dataset').resolve()):
        if destination == protected or destination in protected.parents or protected in destination.parents:
            raise ValueError('Output must not overwrite or be placed inside source data or strict v1')
    originals=read_rows(source)
    by_id={d['doc_id']:d for d in originals}
    if len(by_id)!=len(originals):
        raise ValueError('Duplicate source doc_id')
    strict_rows={d['doc_id']:d for d in read_rows(strict/'documents.jsonl')}
    strict_groups=read_rows(strict/'split_groups.jsonl')
    if any(len(d['disease_labels'])!=1 or d['disease_labels'][0] not in LABELS for d in originals):
        raise ValueError('Expected unchanged single-label 12-class source')
    labels={d['doc_id']:d['disease_labels'][0] for d in originals}
    seen,exposure_files=exposure_inventory(root)
    documents=[];provenance=[];decisions=[];excluded=[];recovery=[]
    for original in originals:
        row,links,ledger=recover_document(original)
        provenance.extend(links);decisions.extend(ledger)
        if len(re.findall(r'\w+',row['text']))<5:
            excluded.append({'doc_id':row['doc_id'],'reason':'fewer_than_5_retained_tokens'})
        else:
            documents.append(row)
        old=strict_rows.get(row['doc_id'],{'text':'','sections':[]})
        recovery.append({'doc_id':row['doc_id'],'strict_characters':len(old['text']),'context_characters':len(row['text']),
                         'strict_hpi':any(s['name']=='hoibenh_quatrinhbenhly' for s in old['sections']),
                         'context_hpi':any(s['name']=='hoibenh_quatrinhbenhly' for s in row['sections'])})
    documents.sort(key=lambda d:d['doc_id'])
    doc_ids={d['doc_id'] for d in documents}
    groups,pairs,similarity=similarity_groups(documents)
    uf=UnionFind(len(groups));index={d:i for i,g in enumerate(groups) for d in g}
    # Same partitions support an honest paired comparison with strict policy A.
    for g in strict_groups:
        members=[d for d in g['doc_ids'] if d in index]
        for d in members[1:]:uf.union(index[members[0]],index[d])
        if g['upstream_development_exposed']:
            seen.update(members)
    raw_templates={}
    for d in documents:
        key=digest(template_text(by_id[d['doc_id']]['text']))
        if key in raw_templates:uf.union(index[d['doc_id']],index[raw_templates[key]])
        else:raw_templates[key]=d['doc_id']
    combined=defaultdict(list)
    for i,g in enumerate(groups):combined[uf.find(i)].extend(g)
    grouping=[{'group_id':'GRP_'+digest('|'.join(sorted(g)))[:16],'doc_ids':sorted(g),
               'upstream_development_exposed':any(d in seen for d in g)} for g in combined.values()]
    grouping.sort(key=lambda g:g['group_id'])
    assignments,wanted,counts=make_partitions(grouping,labels)
    rows_by_split={k:[] for k in ('train','validation','test')}
    assignment_rows=[]
    for g in grouping:
        split=assignments[g['group_id']]
        for d in g['doc_ids']:
            assignment_rows.append({'doc_id':d,'split':split,'group_id':g['group_id'],
                                    'upstream_development_exposed':g['upstream_development_exposed']})
            rows_by_split[split].append(d)
    # Exact source-slice equality, offsets and labels are verified on every record.
    generated={d['doc_id']:d for d in documents}
    all_generated={d['doc_id']:recover_document(d)[0] for d in originals if d['doc_id'] not in doc_ids}
    all_generated.update(generated)
    for p in provenance:
        src=by_id[p['doc_id']]['sections'][p['source_section_index']]['text'][p['source_start']:p['source_end']]
        dst=all_generated[p['doc_id']]['text'][p['output_start']:p['output_end']]
        if src!=dst or digest(src)!=p['source_slice_sha256']:
            raise ValueError('Non-verbatim restoration detected')
    for d in documents:
        assert not d['disease_labels']
        assert all(d['text'][s['doc_start']:s['doc_end']]==s['text'] for s in d['sections'])
    assert len(assignment_rows)==len(documents)==len({a['doc_id'] for a in assignment_rows})
    assert set().union(*(set(v) for v in rows_by_split.values()))==doc_ids
    assignment_by_id={a['doc_id']:a for a in assignment_rows}
    group_overlap=sum(len({assignment_by_id[d]['split'] for d in g['doc_ids']})>1 for g in grouping)
    eval_exposed=sum(a['split']!='train' and a['upstream_development_exposed'] for a in assignment_rows)
    hash_splits=defaultdict(set)
    for d in documents:
        hash_splits[d['content_hash']].add(assignment_by_id[d['doc_id']]['split'])
    exact_overlap=sum(len(v)>1 for v in hash_splits.values())
    if group_overlap or eval_exposed or exact_overlap:
        raise ValueError('Cross-split group, identical feature text or upstream exposure leakage')
    kept_reasons=Counter(p['decision'] for p in provenance)
    report={'version':VERSION,'status':'FROZEN_FOR_EXPLORATORY_FIXED_EXTRACTOR_STUDY_NOT_TEMPORALLY_CERTIFIED',
            'source_documents':len(originals),'documents':len(documents),'excluded_documents':len(excluded),
            'verbatim_source_spans_checked':len(provenance),'verbatim_mismatches':0,'selection_reasons':dict(kept_reasons),
            'hpi_restored_documents':sum(not r['strict_hpi'] and r['context_hpi'] for r in recovery),
            'hpi_absent_after':sum(not r['context_hpi'] for r in recovery if r['doc_id'] in doc_ids),
            'larger_than_strict_documents':sum(r['context_characters']>r['strict_characters'] for r in recovery),
            'groups':len(grouping),'similarity':similarity,'split_seed':SEED,'requested_ratios':{'train':.7,'validation':.15,'test':.15},
            'split_documents':{k:len(v) for k,v in rows_by_split.items()},
            'split_groups':dict(Counter(assignments.values())),
            'per_class':[{'label':label,**{split:counts[split][label] for split in counts},
                          'validation_target':wanted['validation'][label],'test_target':wanted['test'][label]} for label in LABELS],
            'evaluation_exposed_documents':eval_exposed,'group_overlap':group_overlap,
            'exact_feature_overlap':exact_overlap,
            'train_only_exposed_documents':sum(a['upstream_development_exposed'] for a in assignment_rows),
            'retained_information_not_rewritten':True,
            'paired_strict_available':{split:sum(d in strict_rows for d in ids) for split,ids in rows_by_split.items()},
            'test_classes_under_20':[label for label in LABELS if counts['test'][label]<20],
            'missing_split_classes':{split:[label for label in LABELS if not counts[split][label]] for split in counts},
            'limitations':['Verbatim relative to processed/anonymized source, not byte-identical to raw TXT.',
                           'Regex/context proxies cannot certify timing or clinical meaning; only literal source preservation is exhaustively checked.',
                           'Historical target diseases are allowed only with explicit textual evidence, not just a history section title.',
                           'No reliable patient IDs; similarity grouping is approximate, and group-disjoint does not prove patient-disjoint.',
                           'Rare-class test counts are small. Exploratory results are not clinical validation.',
                           'Support-modified measurement units are withheld together rather than stripping away oxygen/treatment context.',
                           'Sections are fragmented deliberately: never concatenate separate snippets into a clinical sentence.']}
    policy={'version':VERSION,'split_seed':SEED,'history_pattern':HISTORY.pattern,'current_pattern':CURRENT.pattern,
            'context_reset_pattern':RESET.pattern,'support_pattern':SUPPORT.pattern,'clinical_prefix_pattern':CLINICAL.pattern,
            'connector_pattern':CONNECTOR.pattern,'measurement_pattern':MEASUREMENT.pattern,
            'extra_treatment_pattern':EXTRA_TREATMENT.pattern,'semicolon_lists':'keep together with their heading and negation',
            'exceptions':['Smoking exposure is not medication use.','Response to pain/stimulation is a neurological examination finding.'],
            'rule_patterns':{k:r.pattern for k,r in RULES.items()},'allowed_sections':sorted(ALLOWED),
            'max_cutoff_scope':'Only safe prefixes, never suffixes following an unsafe event; no generative rewriting',
            'text_source':'artifacts/processed/documents.jsonl','unknown_timing':'withhold flagged unit',
            'source_labels_never_select_content':True,'history_section_alone_is_insufficient':True,
            'upstream_exposed_groups':'train only','paired_strict_baseline':'Reuse context assignments for strict-view cases; no independent re-splitting'}
    output.mkdir(parents=True,exist_ok=True)
    _atomic_write_jsonl(output/'documents.jsonl',documents)
    _atomic_write_jsonl(output/'targets.jsonl',({'doc_id':d['doc_id'],'label':labels[d['doc_id']],'class_id':LABELS.index(labels[d['doc_id']])} for d in documents))
    for name,records in [('source_spans',provenance),('decisions',decisions),('excluded',excluded),('restoration_audit',recovery),('split_groups',grouping),('split_assignments',sorted(assignment_rows,key=lambda a:a['doc_id'])),('near_duplicate_pairs',pairs)]:
        _atomic_write_jsonl(output/(name+'.jsonl'),records)
    for split,ids in rows_by_split.items():
        _atomic_write_jsonl(output/'splits'/(split+'.jsonl'),(generated[d] for d in sorted(ids)))
        _atomic_write_jsonl(output/'split_targets'/(split+'.jsonl'),({'doc_id':d,'label':labels[d],'class_id':LABELS.index(labels[d])} for d in sorted(ids)))
        _atomic_write_jsonl(output/'strict_baseline_splits'/(split+'.jsonl'),(strict_rows[d] for d in sorted(ids) if d in strict_rows))
    _atomic_write_json(output/'policy.json',policy)
    _atomic_write_json(output/'report.json',report)
    _atomic_write_json(output/'upstream_exposure_sources.json',exposure_files)
    _atomic_write_json(output/'input_checksums.json',{'source':sha256_file(source),'strict_documents':sha256_file(strict/'documents.jsonl'),
                                                     'strict_groups':sha256_file(strict/'split_groups.jsonl'),
                                                     'dedup_groups':sha256_file(source.parent/'dedup_groups.jsonl'),
                                                     'code':sha256_file(Path(__file__)),
                                                     'shared_policy_code':sha256_file(Path(__file__).with_name('prediagnosis.py'))})
    _atomic_write_json(output/'checksums.json',{p.relative_to(output).as_posix():sha256_file(p) for p in sorted(output.rglob('*.json*')) if p.name!='checksums.json'})
    return report
