"""Run reviewed KG/Context imports using the running backend (one worker)."""
import argparse
import json
import time
from pathlib import Path

import httpx


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('module', choices=['kg', 'context'])
    p.add_argument('--mode', choices=['validate', 'preview', 'commit', 'retry', 'index'], default='preview')
    p.add_argument('--file', action='append', dest='files')
    p.add_argument('--job', help='Previous preview/commit job id')
    p.add_argument('--confirm', action='store_true', help='Explicitly approve the reviewed files / retry')
    p.add_argument('--base-url', default='http://127.0.0.1:8100')
    p.add_argument('--reports-dir', type=Path)
    args = p.parse_args()
    if args.mode in {'commit', 'retry'} and not (args.job and args.confirm):
        p.error('--job and --confirm are required; review the preview report and source data first')
    if args.mode == 'index' and args.module != 'kg':
        p.error('--mode index is available for KG only')
    base = args.base_url.rstrip('/') + '/api/v1/imports/' + args.module
    try:
        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.post(base + '/jobs', json={'mode': args.mode,
                'source': 'files' if args.files else 'directory', 'files': args.files,
                'previous_job_id': args.job, 'confirmed': args.confirm})
            if not response.is_success:
                print(response.status_code, response.text)
                return 2
            job = response.json()
            print('job_id:', job['job_id'], flush=True)
            last = None
            while True:
                status = (job['status'], job['processed'], job.get('current_file'))
                if status != last:
                    print(f"{job['status']}: {job['processed']}/{job['total']} | {job.get('current_file') or ''}", flush=True)
                    last = status
                if job['status'] in {'completed', 'failed', 'interrupted'}:
                    break
                time.sleep(1)
                response = client.get(base + '/jobs/' + job['job_id'])
                response.raise_for_status()
                job = response.json()
            for item in job['items']:
                print(item['filename'], item['status'], item.get('error', ''))
            for kind, suffix in [('json','.json'),('csv','.csv'),('errors','.errors.csv')]:
                url = base + '/jobs/' + job['job_id'] + '/report?kind=' + kind
                print(url)
                if args.reports_dir:
                    args.reports_dir.mkdir(parents=True, exist_ok=True)
                    result = client.get(url)
                    result.raise_for_status()
                    (args.reports_dir / (job['job_id'] + suffix)).write_bytes(result.content)
            if args.mode == 'preview':
                print('Review source data and report. Commit with --mode commit --job', job['job_id'], '--confirm')
            return (2 if job['status'] != 'completed' else
                    1 if any(job.get(k,0) for k in ['failed','partial','needs_review']) else 0)
    except (httpx.HTTPError, OSError) as exc:
        print('Cannot reach backend or write report:', type(exc).__name__)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
