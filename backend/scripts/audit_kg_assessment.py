"""Read-only structural audit against the running backend. Standard library only."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_page(base_url: str, after: str) -> dict:
    url = base_url.rstrip('/') + '/modules/kg/api/v1/kg/assessment/coverage'
    body = json.dumps({'after_id': after, 'page_size': 100}).encode('utf-8')
    request = Request(url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=120) as response:
        return json.load(response)


def run_audit(base_url: str, model_map: dict | None = None) -> dict:
    rows, cursor, visited = [], '', set()
    while True:
        page = request_page(base_url, cursor)
        if not isinstance(page.get('items'), list):
            raise ValueError('Backend returned an invalid coverage response.')
        rows.extend(page['items'])
        cursor = page.get('next_after_id')
        if not cursor:
            break
        if cursor in visited:
            raise ValueError('Repeated pagination cursor; aborting to avoid an incomplete report.')
        visited.add(cursor)
    report = {'generated_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'live_graph_structure', 'audited_entity_types': page.get('audited_entity_types', []),
              'disease_count': len(rows), 'items': rows,
              'clinical_completeness_assessed': False, 'evidence_text_checked': False}
    if model_map is not None:
        if not isinstance(model_map, dict) or not all(isinstance(k, str) and isinstance(v, list)
                and all(isinstance(i, str) and i.strip() for i in v) for k, v in model_map.items()):
            raise ValueError('Model mapping must be a JSON object: label -> list of KG entity IDs.')
        ids = {item['disease']['id'] for item in rows}
        report['model_mapping'] = [
            {'label': label, 'entity_ids': entity_ids,
             'status': 'unmapped' if not entity_ids else 'ids_present' if set(entity_ids) <= ids else 'missing_ids',
             'missing_entity_ids': sorted(set(entity_ids) - ids)}
            for label, entity_ids in model_map.items()]
        report['model_mapping_note'] = 'Only ID existence checked; label meaning must be verified separately. Include every actual model label.'
    else:
        report['model_mapping_note'] = 'No model mapping supplied; model label coverage not assessed.'
    report['warnings'] = [
        'Missing edges do not mean absence of a clinical relationship.',
        'Counts do not measure diagnostic validity or quality.',
        'A changing database during pagination can change this report; audit a stable import version.',
    ]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8100')
    parser.add_argument('--output', default='kg_assessment_coverage.json')
    parser.add_argument('--model-map', help='Optional JSON: actual model label -> list of KG disease IDs')
    args = parser.parse_args()
    try:
        mapping = json.loads(Path(args.model_map).read_text(encoding='utf-8-sig')) if args.model_map else None
        report = run_audit(args.base_url, mapping)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Saved {output}; {report["disease_count"]} disease nodes audited.')
    except (HTTPError, URLError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'Audit failed ({type(exc).__name__}). Check backend, KG dependencies, mapping and output path.\n')


if __name__ == '__main__':
    main()
