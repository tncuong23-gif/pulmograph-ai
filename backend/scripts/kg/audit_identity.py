"""Read-only audit of already imported entity identities. Never merges or deletes data."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
from app.modules.kg_import.config import Settings, BACKEND_ROOT
from app.modules.kg_import.utils import fold


def audit_rows(rows):
    by_name = defaultdict(list)
    for row in rows:
        by_name[fold(row['canonical_name'])].append(row)
    groups = []
    for name, members in sorted(by_name.items()):
        if len(members) < 2: continue
        types = {e['entity_type'] for e in members}
        groups.append({'normalized_name': name,
                       'kind': 'cross_type' if len(types) > 1 else 'same_name_same_type',
                       'entities': members, 'requires_review': True,
                       'action': 'Kiểm tra loại, thuộc tính và quan hệ nguồn trước khi hợp nhất; không xóa node bằng tên.'})
    return groups


def main():
    from dotenv import load_dotenv
    from neo4j import GraphDatabase
    from app.modules.kg_import.adapters.neo4j import Neo4jKGStore
    from ._common import utf8_stdout
    utf8_stdout()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='data/import_reports/kg/identity-audit.json')
    parser.add_argument('--semantic',action='store_true',help='Also retrieve embedding candidates across all types; requires the current Qdrant index.')
    args=parser.parse_args()
    load_dotenv(BACKEND_ROOT/'.env')
    settings=Settings.from_env()
    rows=[];after='';index=None
    with GraphDatabase.driver(settings.neo4j_uri,auth=(settings.neo4j_username,settings.neo4j_password)) as driver:
        graph=Neo4jKGStore(driver,settings.neo4j_database)
        while True:
            page=graph.list_entities(after,500)
            if not page:break
            rows.extend(page);after=page[-1]['id']
            print(f'Read {len(rows)} entities',flush=True)
    report={'read_only':True,'entity_count':len(rows),'exact_groups':audit_rows(rows),'semantic_pairs':[]}
    if args.semantic:
        from app.modules.kg_import.entity_vector import QdrantEntityIndex
        index=QdrantEntityIndex(settings.entity_embedding)
        known={row['id']:row for row in rows};seen=set()
        try:
            for offset in range(0,len(rows),64):
                batch=rows[offset:offset+64]
                groups=index.suggest_many([(row['canonical_name'],None) for row in batch],limit=10)
                for row,hits in zip(batch,groups):
                    for hit in hits:
                        other=known.get(hit['entity_id'])
                        if not other or other['id']==row['id']:continue
                        pair=tuple(sorted((row['id'],other['id'])))
                        if pair in seen:continue
                        seen.add(pair)
                        report['semantic_pairs'].append({'left':row,'right':other,'score':hit['score'],
                            'cross_type':row['entity_type']!=other['entity_type'],'requires_review':True})
                print(f'Semantic audit {min(offset+64,len(rows))}/{len(rows)}',flush=True)
        finally:index.close()
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Saved {len(report["exact_groups"])} exact-name groups and {len(report["semantic_pairs"])} semantic pairs to {output}')
    return 0


if __name__=='__main__':raise SystemExit(main())
