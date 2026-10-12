"""Explicit, sequential folder imports with durable progress and error reports."""
import csv
import io
import json
import logging
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock, Thread
from uuid import UUID, uuid4

from pydantic import ValidationError
from .core import Input

log = logging.getLogger(__name__)
MAX_BYTES = 8 * 1024 * 1024
MAX_FILES = 10000
TERMINAL = {'completed', 'failed', 'interrupted'}


class BatchBusy(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_name(value, nested=False):
    """Use portable Windows filenames; never accept absolute paths or traversal."""
    if not isinstance(value, str) or not value or len(value) > 240:
        raise ValueError('Tên file không hợp lệ.')
    parts = value.split('/') if nested else [value]
    for part in parts:
        if (part in ('', '.', '..') or part.endswith((' ', '.'))
                or re.search(r'[\\/:<>"|?*\x00-\x1f]', part)
                or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I)):
            raise ValueError('Tên file không hợp lệ; không dùng đường dẫn tuyệt đối hoặc ký tự đặc biệt.')
    if not parts[-1].lower().endswith('.json'):
        raise ValueError('Chỉ nhận file .json.')
    return '/'.join(parts)


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        temp.write_bytes(content)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def csv_cell(value):
    text = str(value or '')
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text


class BatchImporter:
    def __init__(self, service, input_dir, report_dir):
        self.service = service
        self.input_dir = Path(input_dir).absolute()
        self.report_dir = Path(report_dir).absolute()
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.stop = Event()
        self.thread = None
        self.active = None
        self.jobs = {}
        # No resume or database writes on startup. Persist interrupted progress.
        for path in self.report_dir.glob('*.json'):
            try:
                UUID(path.stem)
                job = json.loads(path.read_text(encoding='utf-8'))
                if job['job_id'] != path.stem:
                    continue
                if job['status'] not in TERMINAL:
                    job.update(status='interrupted', finished_at=now(),
                               error='Backend đã dừng. Bấm nạp lại; tài liệu hoàn tất sẽ được bỏ qua.')
                    self._save(job)
                self.jobs[job['job_id']] = job
            except (ValueError, KeyError, TypeError, OSError):
                log.warning('Cannot load RAG batch report %s', path.name, exc_info=True)

    def _path(self, filename):
        filename = safe_name(filename, nested=True)
        path = self.input_dir / filename
        # Reject symlinks even if their targets are still inside the import root.
        cursor = path
        while cursor != self.input_dir.parent:
            if cursor.is_symlink():
                raise ValueError('Không nạp đường dẫn liên kết (symlink).')
            cursor = cursor.parent
        if not path.resolve().is_relative_to(self.input_dir.resolve()):
            raise ValueError('File nằm ngoài thư mục RAG.')
        return path

    def save_upload(self, filename, content):
        with self.lock:
            if self.active:
                raise BatchBusy('Đang có tác vụ nạp RAG. Chờ hoàn tất rồi tải file lên.')
            filename = safe_name(filename)
            if len(content) > MAX_BYTES:
                raise ValueError('JSON tối đa 8 MiB mỗi file.')
            path = self._path(filename)
            atomic_write(path, content)
            return {'filename': filename, 'bytes': len(content), 'saved': True}

    def start(self, source='directory', files=None, mode='commit'):
        with self.lock:
            if self.active:
                raise BatchBusy('Đang có tác vụ nạp RAG. Theo dõi tác vụ hiện tại trước khi nạp tiếp.')
            if self.stop.is_set():
                raise BatchBusy('Backend đang dừng.')
            if source == 'directory':
                # Snapshot filenames, deterministic order; uppercase .JSON is supported.
                paths = sorted(p.relative_to(self.input_dir).as_posix()
                               for p in self.input_dir.rglob('*')
                               if p.suffix.lower() == '.json' and (p.is_file() or p.is_symlink()))
                files = [{'filename': name} for name in paths]
            if not files:
                raise ValueError('Chưa có file JSON để nạp.')
            if len(files) > MAX_FILES:
                raise ValueError(f'Mỗi lượt tối đa {MAX_FILES} file.')
            names = [item['filename'].casefold() for item in files]
            if len(set(names)) != len(names):
                raise ValueError('Danh sách có tên file trùng nhau; hãy đổi tên trước khi nạp.')
            job_id = str(uuid4())
            job = {'job_id': job_id, 'source': source, 'mode': mode, 'status': 'queued',
                   'started_at': now(), 'finished_at': None, 'current_file': None,
                   'total': len(files), 'processed': 0, 'completed': 0, 'skipped': 0, 'failed': 0,
                   'items': [{'filename': item['filename'], 'status': 'pending',
                              **({'upload_error': item['upload_error']} if item.get('upload_error') else {})}
                             for item in files]}
            self._save(job)
            self.jobs[job_id] = job
            self.active = job_id
            self.thread = Thread(target=self._run, args=(job_id,), name='rag-batch', daemon=True)
            self.thread.start()
            return deepcopy(job)

    def _save(self, job):
        atomic_write(self.report_dir / (job['job_id'] + '.json'),
                     json.dumps(job, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8'))
        for suffix, errors_only in [('.csv', False), ('.errors.csv', True)]:
            output = io.StringIO(newline='')
            writer = csv.writer(output)
            writer.writerow(['filename', 'document_id', 'status', 'error', 'warnings', 'chunks', 'propositions'])
            for item in job['items']:
                if errors_only and item['status'] != 'failed':
                    continue
                writer.writerow([csv_cell(item.get(key, '')) for key in
                                 ['filename', 'document_id', 'status', 'error', 'warnings', 'chunks', 'propositions']])
            atomic_write(self.report_dir / (job['job_id'] + suffix), output.getvalue().encode('utf-8-sig'))

    def _run(self, job_id):
        job = self.jobs[job_id]
        seen_ids = {}
        try:
            with self.lock:
                job['status'] = 'running'
                self._save(job)
            for item in job['items']:
                if self.stop.is_set():
                    break
                with self.lock:
                    job['current_file'] = item['filename']
                    self._save(job)
                result = self._process(item, job['mode'], seen_ids)
                with self.lock:
                    item.update(result)
                    job['processed'] += 1
                    job[item['status']] += 1
                    self._save(job)
                log.info('rag.batch job=%s progress=%s/%s file=%s status=%s',
                         job_id, job['processed'], job['total'], item['filename'], item['status'])
            with self.lock:
                job.update(status='completed' if job['processed'] == job['total'] else 'interrupted',
                           current_file=None, finished_at=now())
                if job['status'] == 'interrupted':
                    job['error'] = 'Backend đã dừng; bấm nạp lại để xử lý các file còn lại.'
                self._save(job)
        except Exception:
            log.exception('RAG batch worker failed job=%s', job_id)
            with self.lock:
                job.update(status='failed', current_file=None, finished_at=now(),
                           error='Tác vụ bị dừng; kiểm tra log hoặc quyền ghi thư mục báo cáo rồi nạp lại.')
                try:
                    self._save(job)
                except Exception:
                    log.exception('Cannot persist failed RAG batch report')
        finally:
            with self.lock:
                self.active = None

    def _process(self, item, mode, seen_ids):
        document_id = None
        try:
            if item.get('upload_error'):
                return {'status': 'failed', 'error': item['upload_error'], 'stage': 'upload'}
            path = self._path(item['filename'])
            with path.open('rb') as handle:
                content = handle.read(MAX_BYTES + 1)
            if len(content) > MAX_BYTES:
                raise ValueError('JSON tối đa 8 MiB mỗi file.')
            raw = json.loads(content.decode('utf-8-sig'))
            if not isinstance(raw, dict):
                raise ValueError('JSON phải là một object tài liệu.')
            document_id = raw.get('document', {}).get('document_id') if isinstance(raw.get('document'), dict) else None
            document_id = Input.model_validate(raw).document.document_id
            if isinstance(document_id, str):
                if document_id in seen_ids:
                    raise ValueError(f'document_id trùng với file {seen_ids[document_id]}; hãy giữ một bản đúng.')
                # A malformed first file must not prevent a corrected valid one.
            result = self.service.validate(raw) if mode == 'validate' else self.service.import_data(raw, dry_run=mode == 'dry_run')
            if not result.get('ok', result.get('valid', False)):
                return {'status': 'failed', 'document_id': document_id, 'error': '\n'.join(result.get('errors', [])), 'stage': 'validation'}
            if isinstance(document_id, str):
                seen_ids[document_id] = item['filename']
            return {'status': 'skipped' if result.get('status') == 'skipped' else 'completed',
                    'document_id': document_id, 'result_status': result.get('status', 'valid'),
                    **{key: result[key] for key in ['chunks', 'propositions', 'warnings', 'actions', 'chunking', 'chunking_summary'] if key in result}}
        except ValidationError as exc:
            error = json.dumps(exc.errors(include_url=False, include_input=False, include_context=False), ensure_ascii=False)
        except (ValueError, UnicodeError) as exc:
            error = str(exc)
        except FileNotFoundError:
            error = 'Không tìm thấy file trong thư mục dữ liệu RAG.'
        except Exception as exc:
            log.exception('RAG batch file failed file=%s', item['filename'])
            error = f'{type(exc).__name__}: Không thể đọc file hoặc nạp CSDL. Kiểm tra log backend rồi thử lại.'
        return {'status': 'failed', 'document_id': document_id, 'error': error}

    def get(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise KeyError(job_id)
            return deepcopy(self.jobs[job_id])

    def list(self, limit=20):
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda job: job['started_at'], reverse=True)[:limit]
            return {'active_job_id': self.active, 'items': [deepcopy({key: value for key, value in job.items() if key != 'items'}) for job in jobs]}

    def report(self, job_id, kind):
        self.get(job_id)
        return self.report_dir / (job_id + {'json': '.json', 'csv': '.csv', 'errors': '.errors.csv'}[kind])

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()
