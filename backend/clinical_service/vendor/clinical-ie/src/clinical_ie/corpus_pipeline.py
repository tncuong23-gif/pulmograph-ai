"""Resumable, offline simple-joint corpus extraction and graph-dataset export.

Labels are joined ONLY by the exporter, never passed to the extraction models.
Raw predictions remain available; the graph view withholds ungrounded/conflicting
entities rather than silently treating generated text as source evidence.
"""
from __future__ import annotations

import argparse
import contextlib
import portalocker
import importlib.metadata
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from .cli import _atomic_write_json, _atomic_write_jsonl
from .graph import SCHEMA, build_graphs, cypher_literal, uid
from .prediagnosis import LABELS, digest, read_rows
from .preprocess import iter_segments
from .rules import infer_qualifiers
from .simple_pipeline import (
    INPUT_PREFIX, SimpleJointPipeline, resolve_simple_joint_run, resolve_simplifier_run,
)
from .training import sha256_file

VERSION = 'clinical_graph_corpus_v1'
SPLITS = ('train', 'validation', 'test')
QUALIFIERS = ('assertion', 'temporality', 'severity', 'course', 'laterality')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


@contextlib.contextmanager
def run_lock(output):
    output.mkdir(parents=True, exist_ok=True)
    with (output / '.run.lock').open('a') as handle:
        try:
            portalocker.lock(
                handle,
                portalocker.LOCK_EX | portalocker.LOCK_NB,
            )
        except portalocker.exceptions.LockException as error:
            raise RuntimeError(
                'Another process is writing this run; '
                'use a different output directory'
            ) from error

        try:
            yield
        finally:
            portalocker.unlock(handle)


def validate_dataset(data):
    for name, expected in load_json(data/'checksums.json').items():
        require(sha256_file(data/name)==expected, f'Dataset checksum mismatch: {name}')
    documents=read_rows(data/'documents.jsonl')
    targets={r['doc_id']:r for r in read_rows(data/'targets.jsonl')}
    assignments={r['doc_id']:r for r in read_rows(data/'split_assignments.jsonl')}
    ids={d['doc_id'] for d in documents}
    require(len(documents)==len(ids),'Duplicate input doc_id')
    require(ids==set(targets)==set(assignments),'Dataset ID coverage mismatch')
    for doc in documents:
        require(re.fullmatch(r'[A-Za-z0-9_-]+',doc['doc_id']), 'Unsafe document ID')
        require(doc.get('disease_labels')==[], 'Target labels must not be included in model input')
        require(targets[doc['doc_id']]['label'] in LABELS,'Unknown target label')
        require(assignments[doc['doc_id']]['split'] in SPLITS,'Unknown split')
    return documents, targets, assignments


def select_pilot(data, output):
    require(not output.exists(),'Pilot manifest already exists; keep the frozen selection')
    documents, targets, assignments=validate_dataset(data)
    selected=[]
    for label in LABELS:
        pool=[d for d in documents if targets[d['doc_id']]['label']==label and assignments[d['doc_id']]['split']=='train']
        require(len(pool)>=2, f'Insufficient train cases for {label}')
        ordered=sorted(pool,key=lambda d:(len(d['text']),d['doc_id']))
        # A typical case plus a long, context-rich case, without viewing predictions.
        typical=ordered[len(ordered)//2]
        tail=ordered[len(ordered)*3//4:]
        complex_case=max(tail,key=lambda d:(
            sum(bool(re.search(p,d['text'],re.I)) for p in [r'không',r'tiền sử|cũ',r'\d',r'khó thở',r'âm tính|dương tính']),
            len(d['text']),d['doc_id']))
        selected.extend([typical['doc_id'],complex_case['doc_id']])
    # First five deliberately cover different classes; do not sample final test.
    order=selected[::2]+selected[1::2]
    result={'version':VERSION,'selection':'train_only_2_per_class_typical_and_long_context_rich',
            'data_checksum':sha256_file(data/'checksums.json'),'doc_ids':order,
            'cases':[{'doc_id':d,'label':targets[d]['label'],'split':'train'} for d in order]}
    _atomic_write_json(output,result)
    return {'pilot_documents':len(order),'first_smoke_documents':5,'path':str(output)}


def guarded_qualifiers(text, entity, qualifiers):
    """Withhold unsupported rule attributes; never invent a replacement value."""
    result=dict(qualifiers);withheld=[]
    right=text[entity['end']:entity['end']+80]
    def drop(field, reason):
        if field in result:
            withheld.append({'field':field,'value':result.pop(field),'reason':reason})
    if entity['label'] in {'TIME','TEST','RESULT'}:
        drop('laterality','laterality_not_supported_for_this_entity_type')
    if re.match(r'\s*nhiều\s+(?:ngày|tuần|tháng|năm|giờ|phút)\b',right,re.I):
        drop('severity','duration_many_days_is_not_severity')
    clause=re.split(r'[;.!?\n]',right)[0]
    if re.search(r'(?:tăng|giảm)\s+khi\b',clause,re.I):
        drop('course','positional_change_is_not_longitudinal_improvement')
    return result,withheld


def prepare_clean_document(document, predictions):
    """Keep mention identity, merge only same source-span/type/qualifier duplicates."""
    entities={};evidence=defaultdict(list);triples={};relation_evidence=defaultdict(list)
    warnings=Counter();quarantined=[];raw_entity_count=0;raw_relation_count=0
    for record in predictions:
        warnings.update(record.get('warnings',{}))
        local={}
        for entity in record['entities']:
            raw_entity_count+=1
            start,end=entity.get('start'),entity.get('end')
            reason=None
            if (not isinstance(start,int) or not isinstance(end,int) or not 0<=start<end<=len(document['text'])
                    or document['text'][start:end].casefold()!=entity['text'].casefold()):
                reason='entity_not_grounded_in_source'
            else:
                relative={'text':document['text'][start:end],'label':entity['label'],
                          'start':start-record['doc_start'],'end':end-record['doc_start']}
                require(0<=relative['start']<relative['end']<=len(record['source_text']),'Entity outside source segment')
                source_q=infer_qualifiers(record['source_text'],relative,record.get('section','unknown'))
                source_q,_=guarded_qualifiers(record['source_text'],relative,source_q)
                generated_q,withheld=guarded_qualifiers(record['source_text'],relative,entity.get('qualifiers',{}))
                if any(source_q.get(k)!=generated_q.get(k) for k in QUALIFIERS):
                    reason='source_generated_qualifier_disagreement'
            if reason:
                warnings[reason]+=1
                quarantined.append({'segment_id':record['segment_id'],'entity_id':entity['id'],'reason':reason})
                continue
            qualifiers=generated_q
            if withheld:warnings['unsupported_qualifier_withheld']+=len(withheld)
            key=(start,end,entity['label'],tuple(sorted(qualifiers.items())))
            entity_id='E_'+uid(document['doc_id'],json.dumps(key,ensure_ascii=False))[:24]
            value={**entity,'id':entity_id,'text':document['text'][start:end],'qualifiers':qualifiers}
            if entity_id in entities:
                warnings['duplicate_entity_mentions_merged']+=1
                if value.get('score',0)>entities[entity_id].get('score',0):entities[entity_id]=value
            else:entities[entity_id]=value
            local[entity['id']]=entity_id
            evidence[entity_id].append({'segment_id':record['segment_id'],'simple_sentence_id':entity.get('simple_sentence_id'),
                                        'raw_entity_id':entity['id'],'start':start,'end':end,'withheld_qualifiers':withheld})
        for triple in record.get('triples',[]):
            if triple.get('subject_label')=='CASE':continue  # Regenerated by graph rules.
            raw_relation_count+=1
            if triple['subject_id'] not in local or triple['object_id'] not in local:
                warnings['relation_with_quarantined_endpoint']+=1
                continue
            key=(local[triple['subject_id']],triple['predicate'],local[triple['object_id']])
            value={**triple,'subject_id':key[0],'object_id':key[2]}
            if key in triples:
                warnings['duplicate_relations_merged']+=1
                if value.get('confidence',0)>triples[key].get('confidence',0):triples[key]=value
            else:triples[key]=value
            relation_evidence[key].append({'segment_id':record['segment_id'],'simple_sentence_id':triple.get('simple_sentence_id'),
                                           'raw_relation_id':triple.get('id'),'confidence':triple.get('confidence')})
    clean_triples=[]
    for key,value in sorted(triples.items()):
        value['id']='R_'+uid(*key)[:24]
        value['evidence']=relation_evidence[key]
        clean_triples.append(value)
    clean={'doc_id':document['doc_id'],'entities':[entities[k] for k in sorted(entities)],'triples':clean_triples}
    provenance={'entities':dict(evidence),'relations':{r['id']:r['evidence'] for r in clean_triples},'quarantined':quarantined}
    statistics={'raw_entities':raw_entity_count,'retained_entities':len(entities),'raw_learned_relations':raw_relation_count,
                'retained_learned_relations':len(clean_triples),'quarantined_entities':len(quarantined)}
    return clean,provenance,dict(warnings),statistics


def extract_document(pipeline, document, namespace, segment_batch_size=8):
    started=time.monotonic()
    segments=list(iter_segments(document));predictions=[];token_lengths=[]
    for segment in segments:
        ids=pipeline.simplifier.tokenizer(INPUT_PREFIX+segment['text'],truncation=False)['input_ids']
        token_lengths.append(len(ids))
        require(len(ids)<=pipeline.simplifier.max_source_length,'Input would be silently truncated; needs smaller segmentation')
    for start in range(0,len(segments),segment_batch_size):
        batch=segments[start:start+segment_batch_size]
        result=pipeline.extract_segments(batch)
        require(len(result)==len(batch),'Model dropped input segments')
        for source,prediction in zip(batch,result):
            require(prediction['segment_id']==source['segment_id'],'Prediction/source order mismatch')
            prediction['doc_start']=source['doc_start']
            prediction['doc_end']=source['doc_end']
            predictions.append(prediction)
    clean,provenance,warnings,statistics=prepare_clean_document(document,predictions)
    graph=build_graphs([clean],namespace)[0]
    statistics.update(segments=len(segments),max_source_tokens=max(token_lengths,default=0),
                      generated_sentences=sum(len(p['simple_sentences']) for p in predictions))
    return {'doc_id':document['doc_id'],'input_text_sha256':digest(document['text']),
            'elapsed_seconds':round(time.monotonic()-started,3),'status':'complete',
            'quality_status':'needs_review' if warnings else 'structurally_valid_not_clinically_validated',
            'raw_segments':predictions,'clean_prediction':clean,'provenance':provenance,
            'graph':graph,'warnings':warnings,'statistics':statistics}


def fingerprint(root, data, simplifier, joint, settings, selection):
    paths=[p for directory in [simplifier.run_dir,joint.run_dir] for p in sorted(directory.rglob('*'))
           if p.is_file() and (p.parent.name=='final_model' or p.name in {'metrics.json','run_config.json'})]
    code_names=['corpus_pipeline.py','simple_pipeline.py','preprocess.py','rules.py','inference.py','graph.py','simplification.py','training.py']
    return {'version':VERSION,'dataset_checksums_sha256':sha256_file(data/'checksums.json'),
            'model_files':{str(p.relative_to(root)) if p.is_relative_to(root) else str(p):sha256_file(p) for p in paths},
            'code':{name:sha256_file(Path(__file__).with_name(name)) for name in code_names},
            'packages':{p:importlib.metadata.version(p) for p in ['torch','transformers','gliner','tokenizers']},
            'settings':settings,'selection':selection}


def record_paths(output):
    return sorted((output/'records').glob('*.json'))


def run_extraction(args, root):
    data=args.data_dir.resolve();output=args.output_dir.resolve()
    for protected in [data,root/'models',root/'dataset',root/'artifacts/processed']:
        require(output!=protected and output not in protected.parents and protected not in output.parents,'Unsafe output directory')
    require(args.limit is None or args.limit>0,'--limit must be positive')
    require(args.segment_batch_size>0,'--segment-batch-size must be positive')
    with run_lock(output):
        documents,_,assignments=validate_dataset(data)
        by_id={d['doc_id']:d for d in documents}
        selection=None
        if args.selection:
            selected=load_json(args.selection)
            require(selected['data_checksum']==sha256_file(data/'checksums.json'),'Selection/dataset mismatch')
            selection=selected['doc_ids']
            require(len(selection)==len(set(selection)),'Duplicate selected IDs')
            require(all(d in by_id and assignments[d]['split']=='train' for d in selection),'Pilot must use train only')
        else:
            selection=[d['doc_id'] for split in SPLITS for d in documents if assignments[d['doc_id']]['split']==split]
        simplifier=resolve_simplifier_run(root/'models',args.simplifier_run)
        joint=resolve_simple_joint_run(root/'models',args.joint_run)
        settings={k:getattr(args,k) for k in ['device','simplifier_batch_size','joint_batch_size','segment_batch_size','num_beams','namespace']}
        frozen=fingerprint(root,data,simplifier,joint,settings,selection)
        manifest_path=output/'run_manifest.json'
        if manifest_path.exists():
            require(args.resume,'Run exists; use --resume or a NEW output directory')
            require(load_json(manifest_path)==frozen,'Dataset/model/code/config changed; use a NEW run directory and namespace')
        else:
            require(not record_paths(output),'Records exist without a manifest')
            _atomic_write_json(manifest_path,frozen)
        manifest_hash=sha256_file(manifest_path)
        completed={}
        for path in record_paths(output):
            row=load_json(path)
            require(row['doc_id'] in selection and path.stem==row['doc_id'],'Unexpected output record')
            require(row.get('run_manifest_sha256')==manifest_hash and row.get('status')=='complete','Invalid/incompatible completed record')
            require(row['input_text_sha256']==digest(by_id[row['doc_id']]['text']),'Completed record has different source')
            completed[row['doc_id']]=row['elapsed_seconds']
        pending=[d for d in selection if d not in completed]
        if args.limit:pending=pending[:args.limit]
        print(json.dumps({'selected':len(selection),'already_complete':len(completed),'to_run_now':len(pending),'settings':settings},ensure_ascii=False),flush=True)
        if not pending:return {'status':'NOTHING_PENDING','completed':len(completed)}
        pipeline=SimpleJointPipeline(simplifier,joint,device=args.device,simplifier_batch_size=args.simplifier_batch_size,
                                    joint_batch_size=args.joint_batch_size,num_beams=args.num_beams)
        failures=0;started=time.monotonic();attempted=0;stopped=False
        try:
            for doc_id in pending:
                _atomic_write_json(output/'progress.json',{'state':'running','current_doc_id':doc_id,'completed':len(completed),
                                                          'expected':len(selection),'device':pipeline.device,'updated_unix':time.time()})
                try:
                    row=extract_document(pipeline,by_id[doc_id],args.namespace,args.segment_batch_size)
                    row['run_manifest_sha256']=manifest_hash
                    _atomic_write_json(output/'records'/f'{doc_id}.json',row)
                    completed[doc_id]=row['elapsed_seconds']
                except Exception as error:
                    failures+=1
                    _atomic_write_json(output/'failures'/f'{doc_id}.json',{'doc_id':doc_id,'error_type':type(error).__name__,
                        'error':str(error),'run_manifest_sha256':manifest_hash,'updated_unix':time.time()})
                    print(json.dumps({'failed':doc_id,'error':str(error)},ensure_ascii=False),flush=True)
                    if failures>=args.max_errors:raise
                attempted+=1
                avg=sum(completed.values())/len(completed) if completed else 0
                progress={'state':'running','completed':len(completed),'expected':len(selection),'failures_this_session':failures,
                          'session_attempts':attempted,'elapsed_session_seconds':round(time.monotonic()-started,2),
                          'mean_seconds_per_document':round(avg,3),'eta_seconds':round(avg*(len(selection)-len(completed))),
                          'device':pipeline.device,'updated_unix':time.time()}
                _atomic_write_json(output/'progress.json',progress)
                print(json.dumps(progress,ensure_ascii=False),flush=True)
        except KeyboardInterrupt:
            stopped=True
        finally:
            progress={'state':'complete' if len(completed)==len(selection) else ('paused' if stopped else 'partial'),
                      'completed':len(completed),'expected':len(selection),'failures_this_session':failures,
                      'elapsed_session_seconds':round(time.monotonic()-started,2),'updated_unix':time.time()}
            _atomic_write_json(output/'progress.json',progress)
        return progress


def entity_summary_key(node):
    if node['kind']=='Case':return ('CASE','CASE')+('UNKNOWN',)*len(QUALIFIERS)
    p=node['properties']
    # Lexical inventory only, not a new medical ontology/entity-resolution model.
    text=re.sub(r'\s+',' ',p.get('canonical') or p['text']).strip().casefold()
    return (p['entity_type'],text)+tuple(p.get(k,'UNKNOWN') for k in QUALIFIERS)


def validate_graph(graph):
    ids={n['uid'] for n in graph['nodes']}
    require(len(ids)==len(graph['nodes']),'Duplicate graph node ID')
    edges={e['uid'] for e in graph['edges']}
    require(len(edges)==len(graph['edges']),'Duplicate graph edge ID')
    require(sum(n['kind']=='Case' for n in graph['nodes'])==1,'Expected exactly one Case')
    require(all(e['source'] in ids and e['target'] in ids for e in graph['edges']),'Dangling graph edge')
    for item in graph['nodes']+graph['edges']:
        p=item['properties']
        require(p['doc_id']==graph['doc_id'],'Cross-patient graph component')
        require(not {'disease_label','class_id','split','section','segment_id'}.intersection(p),'Label or segment in feature graph')


def export_corpus(args, root):
    data=args.data_dir.resolve();output=args.output_dir.resolve()
    with run_lock(output):
        documents,targets,assignments=validate_dataset(data)
        by_id={d['doc_id']:d for d in documents}
        manifest=load_json(output/'run_manifest.json');manifest_hash=sha256_file(output/'run_manifest.json')
        require(manifest['dataset_checksums_sha256']==sha256_file(data/'checksums.json'),'Export dataset differs from run')
        for name, expected_hash in manifest.get('code',{}).items():
            require(sha256_file(Path(__file__).with_name(name))==expected_hash,'Extraction code changed; export with the frozen code version')
        expected=set(manifest['selection']);paths=record_paths(output)
        require(args.allow_partial or len(paths)==len(expected),'Run incomplete; use --allow-partial ONLY for pilot/interim exports')
        sums={};denominators=Counter();counts=Counter();warning_counts=Counter();durations=[];seen=set()
        export=output/'exports';export.mkdir(exist_ok=True)
        # Streaming output bounds memory. A completion marker is written last;
        # users must not import an interrupted export without re-running export.
        _atomic_write_json(export/'manifest.json',{'status':'EXPORT_IN_PROGRESS'})
        with contextlib.ExitStack() as stack:
            handles={}
            for name in [*(f'graphs/{s}.jsonl' for s in SPLITS),'graph_index.jsonl','entities.jsonl','relations.jsonl','provenance.jsonl']:
                path=export/name;path.parent.mkdir(parents=True,exist_ok=True)
                handles[name]=stack.enter_context(path.open('w',encoding='utf-8'))
            neo=export/'neo4j';neo.mkdir(exist_ok=True)
            (neo/'schema.cypher').write_text(SCHEMA,encoding='utf-8')
            cypher=stack.enter_context((neo/'import.cypher').open('w',encoding='utf-8'));cypher.write(SCHEMA)
            def emit(name,value):handles[name].write(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n')
            def aggregate(scope,label,kind,key,doc_id):
                item=sums.setdefault((scope,label,kind,key),{'occurrences':0,'documents':set()})
                item['occurrences']+=1;item['documents'].add(doc_id)
            for path in paths:
                row=load_json(path);doc_id=row['doc_id'];graph=row['graph']
                require(doc_id in expected and doc_id not in seen and path.stem==doc_id,'Unexpected/duplicate record')
                require(row['run_manifest_sha256']==manifest_hash and row['status']=='complete','Record not complete or wrong run')
                require(row['input_text_sha256']==digest(by_id[doc_id]['text']),'Source mismatch')
                validate_graph(graph)
                require(graph==build_graphs([row['clean_prediction']],manifest['settings']['namespace'])[0],'Graph differs from clean predictions')
                seen.add(doc_id);split=assignments[doc_id]['split'];label=targets[doc_id]['label']
                for scope in (split,'all'):denominators[(scope,label)]+=1
                counts['graphs']+=1;counts['nodes']+=len(graph['nodes']);counts['edges']+=len(graph['edges'])
                counts['empty_graphs']+=len(graph['nodes'])==1
                warning_counts.update(row['warnings']);durations.append(row['elapsed_seconds'])
                emit(f'graphs/{split}.jsonl',graph)
                case=next(n for n in graph['nodes'] if n['kind']=='Case')
                metadata={'doc_id':doc_id,'disease_label':label,'class_id':targets[doc_id]['class_id'],'split':split}
                emit('graph_index.jsonl',{'graph_id':case['uid'],**metadata,'namespace':graph['namespace'],'quality_status':row['quality_status']})
                nodes={n['uid']:n for n in graph['nodes']}
                for node in graph['nodes']:
                    if node['kind']=='Entity':
                        emit('entities.jsonl',{'entity_uid':node['uid'],**metadata,**node['properties']})
                        for scope in (split,'all'):aggregate(scope,label,'entity',entity_summary_key(node),doc_id)
                for edge in graph['edges']:
                    emit('relations.jsonl',{'relation_uid':edge['uid'],**metadata,**edge,
                         'subject':entity_summary_key(nodes[edge['source']]),'object':entity_summary_key(nodes[edge['target']])})
                    origin=edge['properties']['source']
                    for scope in (split,'all'):
                        aggregate(scope,label,'relation',(entity_summary_key(nodes[edge['source']]),edge['predicate'],entity_summary_key(nodes[edge['target']]),origin),doc_id)
                        aggregate(scope,label,'predicate',(edge['predicate'],origin),doc_id)
                emit('provenance.jsonl',{'doc_id':doc_id,**row['provenance'],'warnings':row['warnings']})
                for kind in ('Case','Entity'):
                    node_rows=[n for n in graph['nodes'] if n['kind']==kind]
                    for start in range(0,len(node_rows),250):
                        cypher.write(f'UNWIND {cypher_literal(node_rows[start:start+250])} AS row\nMERGE (n:ClinicalNode:{kind} {{uid: row.uid}})\nSET n = row.properties, n.uid = row.uid;\n')
                for predicate in sorted({e['predicate'] for e in graph['edges']}):
                    edges=[e for e in graph['edges'] if e['predicate']==predicate]
                    for start in range(0,len(edges),250):
                        cypher.write(f'UNWIND {cypher_literal(edges[start:start+250])} AS row\nMATCH (s:ClinicalNode {{uid: row.source}}), (t:ClinicalNode {{uid: row.target}})\nMERGE (s)-[r:{predicate} {{uid: row.uid}}]->(t)\nSET r = row.properties, r.uid = row.uid;\n')
        for scope in (*SPLITS,'all'):
            for kind in ('entity','relation','predicate'):
                summary=[]
                for (s,label,k,key),value in sorted(sums.items()):
                    if s!=scope or k!=kind:continue
                    summary.append({'disease_label':label,'key':key,'occurrences':value['occurrences'],
                        'document_count':len(value['documents']),'class_documents':denominators[(scope,label)],
                        'document_prevalence':len(value['documents'])/denominators[(scope,label)],
                        'doc_ids':sorted(value['documents'])})
                _atomic_write_jsonl(export/'summaries'/scope/f'{kind}_by_label.jsonl',summary)
        missing=sorted(expected-seen)
        report={'status':'COMPLETE' if not missing else 'PARTIAL','expected_documents':len(expected),
            'dataset_documents':len(documents),'selection_is_full_dataset':expected==set(by_id),
            'completed_documents':len(seen),'missing_doc_ids':missing,'counts':dict(counts),'warnings':dict(warning_counts),
            'per_class':[{'label':label,**{s:denominators[(s,label)] for s in (*SPLITS,'all')}} for label in LABELS],
            'inference_seconds':round(sum(durations),3),'mean_seconds_per_document':round(sum(durations)/len(durations),3) if durations else None,
            'validation':'Offline structure and evidence checks, not live Neo4j or clinical accuracy',
            'inventory_key_fields':['entity_type','normalized_text','assertion','temporality','severity','course','laterality'],
            'relation_key_fields':['subject_entity_key','predicate','object_entity_key','source'],
            'feature_policy':'Only graphs/ is feature input; graph_index and all inventories contain labels and MUST NOT enter model features',
            'all_summary_usage':'Descriptive only. Fit vocabulary/probabilities/feature selection from TRAIN only.'}
        _atomic_write_json(export/'manifest.json',report)
        _atomic_write_json(export/'checksums.json',{str(p.relative_to(export)):sha256_file(p) for p in sorted(export.rglob('*')) if p.is_file() and p.name!='checksums.json'})
    return report


def audit_export(output, allow_partial=False):
    export=output/'exports';report=load_json(export/'manifest.json')
    require(report['status'] in ('COMPLETE','PARTIAL'),'Export was interrupted; re-run export')
    require(allow_partial or report['status']=='COMPLETE','Incomplete export')
    for name,expected in load_json(export/'checksums.json').items():
        require(sha256_file(export/name)==expected, f'Export checksum mismatch: {name}')
    index=read_rows(export/'graph_index.jsonl');index_by_id={r['doc_id']:r for r in index}
    require(len(index)==len(index_by_id),'Duplicate graph index ID')
    seen=set();node_count=edge_count=0
    for split in SPLITS:
        with (export/'graphs'/f'{split}.jsonl').open() as handle:
            for line in handle:
                graph=json.loads(line);doc_id=graph['doc_id']
                validate_graph(graph)
                require(doc_id not in seen and doc_id in index_by_id,'Duplicate/unindexed graph')
                require(index_by_id[doc_id]['split']==split,'Graph/index split mismatch')
                require(index_by_id[doc_id]['disease_label'] in LABELS,'Invalid target label')
                require(any(n['uid']==index_by_id[doc_id]['graph_id'] and n['kind']=='Case' for n in graph['nodes']),'Graph/index Case mismatch')
                seen.add(doc_id);node_count+=len(graph['nodes']);edge_count+=len(graph['edges'])
    require(seen==set(index_by_id),'Index/graph coverage mismatch')
    require(len(seen)==report['completed_documents']==report['counts']['graphs'],'Graph count mismatch')
    require(node_count==report['counts']['nodes'] and edge_count==report['counts']['edges'],'Node/edge count mismatch')
    return {'status':'PASS','export_status':report['status'],'graphs':len(seen),'nodes':node_count,'edges':edge_count,
            'full_dataset':report['selection_is_full_dataset'],'clinical_accuracy':'not_measured','neo4j_execution':'not_tested'}


def main(argv=None):
    root=Path(__file__).resolve().parents[2]
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    default_data=root/'artifacts/classification/prediagnosis_v2'
    pilot=sub.add_parser('select-pilot');pilot.add_argument('--data-dir',type=Path,default=default_data);pilot.add_argument('--output',type=Path,required=True)
    run=sub.add_parser('run')
    export=sub.add_parser('export')
    for p in (run,export):
        p.add_argument('--data-dir',type=Path,default=default_data)
        p.add_argument('--output-dir',type=Path,required=True)
    run.add_argument('--selection',type=Path)
    run.add_argument('--simplifier-run',type=Path,default=root/'models/vit5_simple_v1_3')
    run.add_argument('--joint-run',type=Path,default=root/'models/relex_simple_joint_v1_3')
    run.add_argument('--namespace',required=True)
    run.add_argument('--device',choices=('cpu','mps','auto','cuda'),default='cpu')
    run.add_argument('--simplifier-batch-size',type=int,default=4)
    run.add_argument('--joint-batch-size',type=int,default=8)
    run.add_argument('--segment-batch-size',type=int,default=8)
    run.add_argument('--num-beams',type=int,default=4)
    run.add_argument('--limit',type=int)
    run.add_argument('--resume',action='store_true')
    run.add_argument('--max-errors',type=int,default=3)
    export.add_argument('--allow-partial',action='store_true')
    audit=sub.add_parser('audit');audit.add_argument('--output-dir',type=Path,required=True);audit.add_argument('--allow-partial',action='store_true')
    status=sub.add_parser('status');status.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.command=='select-pilot':result=select_pilot(args.data_dir,args.output)
    elif args.command=='run':result=run_extraction(args,root)
    elif args.command=='export':result=export_corpus(args,root)
    elif args.command=='audit':result=audit_export(args.output_dir,args.allow_partial)
    else:
        progress=args.output_dir/'progress.json'
        result=load_json(progress) if progress.exists() else {'state':'not_started'}
        result['note']='Snapshot only; running state may be stale after abrupt process termination.'
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return 0
