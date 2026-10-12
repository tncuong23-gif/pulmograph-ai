"""Submit a folder job to the running backend, sharing its encoder and store."""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx


def main(argv=None):
    parser = argparse.ArgumentParser(description='Nạp JSON từ backend/data/import/rag qua backend đang chạy.')
    parser.add_argument('--base-url', default='http://127.0.0.1:8100')
    parser.add_argument('--file', action='append', help='Chỉ nạp tên file trong thư mục RAG; có thể lặp lại.')
    parser.add_argument('--mode', choices=['commit', 'dry_run', 'validate'], default='commit')
    parser.add_argument('--reports-dir', type=Path, help='Tải báo cáo JSON, CSV và CSV lỗi về thư mục này.')
    args = parser.parse_args(argv)
    api = args.base_url.rstrip('/') + '/modules/rag/api/v1/rag'
    payload = {'source': 'files' if args.file else 'directory', 'mode': args.mode,
               'files': [{'filename': name} for name in args.file or []]}
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(api + '/batch/jobs', json=payload)
            response.raise_for_status()
            job = response.json()
            job_url = api + '/batch/jobs/' + job['job_id']
            print('Tác vụ:', job['job_id'], '| Số file:', job['total'], flush=True)
            previous = None
            while True:
                response = client.get(job_url)
                response.raise_for_status()
                job = response.json()
                progress = (job['processed'], job['current_file'], job['status'])
                if progress != previous:
                    print(f"[{job['processed']}/{job['total']}] {job['status']} | "
                          f"xong={job['completed']} không đổi={job['skipped']} lỗi={job['failed']} | "
                          f"{job['current_file'] or ''}", flush=True)
                    previous = progress
                if job['status'] in ('completed', 'failed', 'interrupted'):
                    break
                time.sleep(1)
            if args.reports_dir:
                args.reports_dir.mkdir(parents=True, exist_ok=True)
                for kind, suffix in [('json', '.json'), ('csv', '.csv'), ('errors', '.errors.csv')]:
                    response = client.get(job_url + '/report', params={'kind': kind})
                    response.raise_for_status()
                    path = args.reports_dir / (job['job_id'] + suffix)
                    path.write_bytes(response.content)
                    print('Báo cáo:', path.resolve())
            else:
                print('Báo cáo JSON:', job_url + '/report?kind=json')
                print('Báo cáo lỗi:', job_url + '/report?kind=errors')
            return 2 if job['status'] != 'completed' else (1 if job['failed'] else 0)
    except httpx.HTTPStatusError as exc:
        print('Không thể thực hiện:', exc.response.status_code, exc.response.text, file=sys.stderr)
    except (httpx.HTTPError, ValueError, KeyError, OSError) as exc:
        print('Không thể thực hiện:', str(exc), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
