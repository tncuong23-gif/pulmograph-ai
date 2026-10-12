"""One asynchronous worker per module; SQLite journals each completed file.

Source files are pinned by SHA256 between review and commit. A restarted backend
marks outstanding work interrupted; it never starts a write on its own.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.modules.rag.batch import atomic_write, csv_cell, now, safe_name

log = logging.getLogger('uvicorn.error')
MAX_FILES = 10000
MAX_BYTES = 20 * 1024 * 1024
FINISHED = {'completed', 'failed', 'interrupted'}
COUNTS = ('completed', 'skipped', 'failed', 'partial', 'needs_review')


class ImportBusy(ValueError):
    pass


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class BatchManager:
    def __init__(self, module, adapter, input_dir, report_dir):
        self.module, self.adapter = module, adapter
        self.input_dir, self.report_dir = Path(input_dir).absolute(), Path(report_dir).absolute()
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.report_dir / 'jobs.sqlite3', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS items (job TEXT, position INTEGER, data TEXT NOT NULL,
            PRIMARY KEY(job, position));
        ''')
        self.reviews = None
        if module == 'kg':
            from app.modules.kg_import.review_store import DocumentReviewStore
            self.reviews = DocumentReviewStore(self.report_dir)
        self.active = None
        self.task = None
        self.stopping = False
        for jid, data in self.db.execute('SELECT id,data FROM jobs').fetchall():
            job = json.loads(data)
            if job['status'] not in FINISHED:
                job.update(status='interrupted', finished_at=now(), current_file=None,
                           error='Backend đã dừng. Xem báo cáo rồi chủ động thử lại các file chưa hoàn tất.')
                for row in self._items(jid):
                    if row['status'] in {'pending', 'running'}:
                        row.update(status='partial' if job['mode'] in {'commit', 'retry'} else 'failed',
                                   stage='interrupted', error='Tiến trình bị ngắt; cần kiểm tra/nạp lại file.')
                        self._put_item(jid, row)
                self._counts(job)
                self._put_job(job)

    def _busy(self):
        if self.active or self.stopping:
            raise ImportBusy('Đang có tác vụ hoặc backend đang dừng. Chờ hoàn tất trước khi tải/nạp tiếp.')

    def path(self, filename):
        name = safe_name(filename, nested=True)
        path = self.input_dir / name
        cursor = path
        while True:
            if cursor.is_symlink() or (hasattr(cursor, 'is_junction') and cursor.is_junction()):
                raise ValueError('Không nhận symlink hoặc junction trong đường dẫn dữ liệu.')
            if cursor == self.input_dir.parent:
                break
            cursor = cursor.parent
        if not path.resolve().is_relative_to(self.input_dir.resolve()):
            raise ValueError('Đường dẫn nằm ngoài thư mục nhập dữ liệu.')
        return path

    def upload(self, filename, content):
        self._busy()
        if len(content) > MAX_BYTES:
            raise ValueError('Mỗi file tối đa 20 MiB.')
        path = self.path(filename)
        atomic_write(path, content)
        return {'filename': filename, 'bytes': len(content), 'saved': True}

    def read(self, filename, expected=None):
        with self.path(filename).open('rb') as handle:
            content = handle.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError('Mỗi file tối đa 20 MiB.')
        sha = hashlib.sha256(content).hexdigest()
        if expected and expected != sha:
            raise ValueError('File đã thay đổi sau khi xem trước. Hãy xem trước và xác nhận lại.')
        raw = json.loads(content.decode('utf-8-sig'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('JSON chứa số không hữu hạn.')))
        if not isinstance(raw, dict):
            raise ValueError('Mỗi file phải là một JSON object, không phải mảng tài liệu.')
        return raw, sha

    def _items(self, jid):
        return [json.loads(row[0]) for row in self.db.execute('SELECT data FROM items WHERE job=? ORDER BY position', (jid,))]

    def _put_item(self, jid, item):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO items VALUES (?,?,?)', (jid, item['position'], dump(item)))

    def _put_job(self, job):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?)', (job['job_id'], dump(job)))

    def _counts(self, job):
        rows = self._items(job['job_id'])
        job.update({key: sum(r['status'] == key for r in rows) for key in COUNTS})
        job['processed'] = sum(r['status'] in COUNTS for r in rows)

    def get(self, jid):
        row = self.db.execute('SELECT data FROM jobs WHERE id=?', (jid,)).fetchone()
        if row is None:
            raise KeyError(jid)
        job = json.loads(row[0])
        job['items'] = self._items(jid)
        return job

    def list(self):
        rows = [json.loads(row[0]) for row in self.db.execute('SELECT data FROM jobs')]
        return {'active_job_id': self.active,
                'items': sorted(rows, key=lambda j: j['started_at'], reverse=True)[:30]}

    def start(self, *, mode='preview', source='directory', files=None, previous_job_id=None, confirmed=False, file_errors=None):
        self._busy()
        if mode not in {'validate', 'preview', 'commit', 'retry', 'index'}:
            raise ValueError('Chế độ không hợp lệ.')
        if source not in {'directory', 'files'}:
            raise ValueError('Nguồn không hợp lệ.')
        previous = None
        if file_errors and (mode not in {'validate', 'preview'} or source != 'files'):
            raise ValueError('Lỗi tải file chỉ dùng cho lượt kiểm tra/xem trước các file được chọn.')
        if mode in {'commit', 'retry'}:
            if not confirmed or not previous_job_id:
                raise ValueError('Cần xem trước và xác nhận rõ ràng trước khi ghi dữ liệu.')
            previous = self.get(previous_job_id)
            valid = (mode == 'commit' and previous['mode'] == 'preview' and previous['status'] == 'completed') or (
                mode == 'retry' and previous['mode'] in {'commit', 'retry'} and previous['status'] in FINISHED
                and previous.get('confirmed_at'))
            if not valid:
                raise ValueError('Lượt trước chưa sẵn sàng để xác nhận/thử lại.')
            allowed = {'completed'} if mode == 'commit' else {'failed', 'partial'}
            selected = set(files) if files is not None else None
            rows = [dict(item) for item in previous['items'] if item['status'] in allowed
                    and (selected is None or item['filename'] in selected)]
            if selected and selected != {item['filename'] for item in rows}:
                raise ValueError('Chỉ chọn file hợp lệ trong lượt xem trước hoặc file lỗi của lượt nạp.')
            for item in rows:
                if not item.get('sha256'):
                    raise ValueError('File chưa có bản xem trước hợp lệ. Hãy xem trước lại.')
            source = 'files'
        elif mode == 'index':
            if self.module != 'kg':
                raise ValueError('Chỉ mục Qdrant thực thể chỉ dành cho KG.')
            rows = [{'filename': 'KG_INDEX.json'}]
        else:
            if source == 'directory':
                files = []
                for base, dirs, names in os.walk(self.input_dir, followlinks=False):
                    dirs[:] = sorted(d for d in dirs if not (Path(base)/d).is_symlink()
                                     and not (hasattr(Path(base)/d, 'is_junction') and (Path(base)/d).is_junction()))
                    for name in sorted(names):
                        if name.lower().endswith('.json'):
                            files.append((Path(base)/name).relative_to(self.input_dir).as_posix())
                            if len(files) > MAX_FILES:
                                raise ValueError(f'Tối đa {MAX_FILES} file mỗi lượt.')
            rows = [{'filename': name} for name in files or []]
        if not rows or len(rows) > MAX_FILES:
            raise ValueError(f'Cần từ 1 đến {MAX_FILES} file phù hợp.')
        names = [safe_name(r['filename'], nested=True).casefold() for r in rows]
        if len(names) != len(set(names)):
            raise ValueError('Tên file trùng nhau trong cùng lượt.')
        jid = str(uuid4())
        job = {'job_id': jid, 'module': self.module, 'mode': mode, 'source': source, 'status': 'queued',
               'started_at': now(), 'finished_at': None, 'current_file': None, 'total': len(rows),
               'processed': 0, **{key: 0 for key in COUNTS}, 'previous_job_id': previous_job_id,
               'confirmed_at': now() if mode in {'commit', 'retry'} else None}
        for pos, old in enumerate(rows):
            item = {'position': pos, 'filename': old['filename'], 'status': 'pending'}
            if file_errors and old['filename'] in file_errors:
                item['upload_error'] = str(file_errors[old['filename']])[:400]
            if previous:
                item['sha256'] = old['sha256']
                if mode == 'retry' and old.get('import_id'):
                    item['retry_import_id'] = old['import_id']
            self._put_item(jid, item)
        self._put_job(job)
        self.active = jid
        self.task = asyncio.create_task(self._run(job), name=f'{self.module}-batch')
        return self.get(jid)

    async def _run(self, job):
        seen = {}
        try:
            job['status'] = 'running'
            self._put_job(job)
            for item in self._items(job['job_id']):
                if self.stopping:
                    break
                item['status'] = 'running'
                job['current_file'] = item['filename']
                self._put_item(job['job_id'], item)
                self._put_job(job)
                try:
                    if item.get('upload_error'):
                        item['stage'] = 'upload'
                        raise ValueError(item['upload_error'])
                    if job['mode'] == 'index':
                        item.update(await self.adapter.bootstrap())
                        self._put_item(job['job_id'], item)
                        job['processed'] += 1
                        job[item['status']] += 1
                        self._put_job(job)
                        continue
                    raw, sha = self.read(item['filename'], item.get('sha256'))
                    item['sha256'] = sha
                    identity = self.adapter.identity(raw)
                    item['record_id'] = identity
                    if identity in seen:
                        raise ValueError(f'ID trùng với file {seen[identity]}; giữ một bản trong mỗi lượt.')
                    result = await self.adapter.process(raw, mode=job['mode'], job_id=job['job_id'],
                                                        sha=sha, retry_import_id=item.get('retry_import_id'))
                    item.update(result)
                    if self.reviews and hasattr(self.adapter, 'review_profile'):
                        item.update(self.reviews.status(raw, self.adapter.review_profile(), needs_review=item['status'] == 'needs_review'))
                    if item['status'] in {'completed', 'skipped', 'partial', 'needs_review'}:
                        seen[identity] = item['filename']
                except ValidationError as exc:
                    item.update(status='failed', stage='validation', error=dump(exc.errors(include_input=False, include_context=False, include_url=False)))
                except (ValueError, UnicodeError) as exc:
                    item.update(status='failed', error=str(exc))
                except FileNotFoundError:
                    item.update(status='failed', stage='source', error='Không tìm thấy file đầu vào.')
                except Exception as exc:
                    log.exception('batch.file_failed module=%s job=%s file=%s', self.module, job['job_id'], item['filename'])
                    item.update(status='failed', error=f'{type(exc).__name__}: Không xử lý được file; kiểm tra log và kết nối CSDL.')
                self._put_item(job['job_id'], item)
                job['processed'] += 1
                job[item['status']] += 1
                self._put_job(job)
                log.info('batch.progress module=%s job=%s progress=%s/%s status=%s', self.module,
                         job['job_id'], job['processed'], job['total'], item['status'])
                await asyncio.sleep(0)
            job.update(status='completed' if job['processed'] == job['total'] else 'interrupted',
                       finished_at=now(), current_file=None)
            if job['status'] == 'interrupted':
                for item in self._items(job['job_id']):
                    if item['status'] in {'pending', 'running'}:
                        item.update(status='failed', stage='interrupted', error='Chưa xử lý vì backend đã dừng.')
                        self._put_item(job['job_id'], item)
                self._counts(job)
            self._put_job(job)
            self.report(job['job_id'], 'json')
            self.report(job['job_id'], 'csv')
            self.report(job['job_id'], 'errors')
        except Exception:
            log.exception('batch.worker_failed module=%s job=%s', self.module, job['job_id'])
            job.update(status='failed', finished_at=now(), error='Tác vụ bị dừng. Kiểm tra quyền ghi/dung lượng và log backend.')
            self._put_job(job)
        finally:
            self.active = None

    async def review(self, jid, position):
        job = self.get(jid)
        if job['mode'] != 'preview' or job['status'] != 'completed':
            raise ValueError('Chỉ mở chi tiết của lượt xem trước đã hoàn tất.')
        item = job['items'][position]
        if item['status'] not in {'completed', 'needs_review'}:
            raise ValueError('File chưa xem trước thành công.')
        raw, _ = self.read(item['filename'], item['sha256'])
        result = await self.adapter.review(raw)
        if self.reviews:
            result.update(self.reviews.status(raw, self.adapter.review_profile(), needs_review=bool(result['plan'].get('entity_candidates'))))
        return result

    async def decisions(self, jid, position, decisions):
        self._busy()
        if self.module != 'kg':
            raise ValueError('Lựa chọn gộp thực thể chỉ dành cho KG.')
        job = self.get(jid)
        if job['mode'] != 'preview' or job['status'] != 'completed':
            raise ValueError('Cần xem trước hoàn tất.')
        item = job['items'][position]
        if item['status'] not in {'completed', 'needs_review'}:
            raise ValueError('File chưa xem trước thành công.')
        raw, _ = self.read(item['filename'], item.get('sha256'))
        updated = await self.adapter.decisions(raw, decisions)
        preview = await self.adapter.review(updated, refresh=True)
        if preview['plan'].get('entity_candidates'):
            raise ValueError('Có thêm thực thể cần duyệt. Mở lại tài liệu để xem các ứng viên mới.')
        # An active job might have started while the graph lookup was awaited.
        self._busy()
        self.read(item['filename'], item['sha256'])
        self.upload(item['filename'], (dump(updated) + '\n').encode('utf-8'))
        _, sha = self.read(item['filename'])
        receipt = self.reviews.mark(updated, self.adapter.review_profile())
        item.update(receipt, sha256=sha, status='completed', candidate_count=0, error='',
                    statistics={k: preview['plan'][k] for k in ['entities', 'relations', 'document_exists'] if k in preview['plan']})
        self._put_item(jid, item)
        job.pop('items', None)
        self._counts(job)
        self._put_job(job)
        return {'saved': True, 'filename': item['filename'], 'item': item,
                'message': 'Đã duyệt và lưu tài liệu. Có thể chọn file này để xác nhận nạp ngay.'}

    def report(self, jid, kind):
        job = self.get(jid)
        if kind == 'json':
            data, suffix = json.dumps(job, ensure_ascii=False, indent=2).encode('utf-8'), '.json'
        else:
            if kind not in {'csv', 'errors'}:
                raise ValueError('Loại báo cáo không hợp lệ.')
            output = io.StringIO(newline='')
            writer = csv.writer(output)
            keys = ['filename', 'record_id', 'status', 'stage', 'error', 'warning', 'import_id', 'statistics', 'review_status', 'reviewed_at', 'review_decision_count', 'elapsed_seconds']
            writer.writerow(keys)
            for item in job['items']:
                if kind == 'errors' and item['status'] not in {'failed', 'partial', 'needs_review'}:
                    continue
                writer.writerow([csv_cell(dump(item[k]) if isinstance(item.get(k), (dict, list)) else item.get(k, '')) for k in keys])
            data, suffix = output.getvalue().encode('utf-8-sig'), '.csv' if kind == 'csv' else '.errors.csv'
        path = self.report_dir / (job['job_id'] + suffix)
        atomic_write(path, data)
        return path

    async def close(self):
        self.stopping = True
        if self.task:
            await self.task
        self.db.close()
        if self.reviews: self.reviews.close()
