import json
import time
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app.modules.rag.batch import BatchBusy, BatchImporter, MAX_BYTES, safe_name
from app.modules.rag.core import ChunkConfig, DemoEncoder
from app.modules.rag.main import create_app
from app.modules.rag.service import Service
from app.modules.rag.storage import DemoStore


def document(doc_id='DOC_A', text='Ho và khó thở là triệu chứng cần đánh giá.'):
    return {'schema_version': '1.0', 'document': {'document_id': doc_id, 'title': 'Nguồn kiểm thử',
        'document_type': 'test', 'language': 'vi', 'sections': [{'section_id': 'SEC', 'title': 'Mục',
        'paragraphs': [{'paragraph_id': 'PAR', 'sentences': [{'sentence_id': 'SENT', 'text': text}]}]}]}}


@pytest.fixture
def service():
    value = Service(DemoStore(':memory:'), DemoEncoder(), ChunkConfig(), 'demo')
    yield value
    value.store.close()


def wait(manager, job_id):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        job = manager.get(job_id)
        if job['status'] in ('completed', 'failed', 'interrupted'):
            manager.thread.join(timeout=1)
            return job
        time.sleep(.005)
    pytest.fail('Batch worker did not finish')


def save(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8-sig')


def test_folder_continues_after_bad_json_schema_and_refs_and_reports_ids(tmp_path, service):
    root = tmp_path/'rag'
    save(root/'01.json', document())
    (root/'02.json').write_text('{not json')
    save(root/'03.json', {'document': {'document_id': 'BROKEN_SCHEMA'}})
    bad = document('BROKEN_REFS')
    bad['propositions'] = [{'id': 'P', 'text': 'Ho.', 'evidence': [{'sentence_id': 'NOT_FOUND'}]}]
    save(root/'04.json', bad)
    save(root/'nested/05.JSON', document('DOC_B'))
    (root/'ignore.txt').write_text('ignore')
    manager = BatchImporter(service, root, tmp_path/'reports')
    job = wait(manager, manager.start()['job_id'])
    assert (job['total'], job['processed'], job['completed'], job['failed']) == (5, 5, 2, 3)
    assert [item['filename'] for item in job['items']] == ['01.json', '02.json', '03.json', '04.json', 'nested/05.JSON']
    assert job['items'][2]['document_id'] == 'BROKEN_SCHEMA'
    assert 'NOT_FOUND' in job['items'][3]['error']
    assert {row['document_id'] for row in service.store.documents()} == {'DOC_A', 'DOC_B'}
    report = json.loads(manager.report(job['job_id'], 'json').read_text())
    assert report == job and 'vector' not in json.dumps(report)
    errors = manager.report(job['job_id'], 'errors').read_text(encoding='utf-8-sig')
    assert 'BROKEN_REFS' in errors and '01.json' not in errors
    assert manager.report(job['job_id'], 'csv').read_bytes().startswith(b'\xef\xbb\xbf')
    manager.close()


def test_second_run_skips_unchanged_and_single_repaired_file_imports(tmp_path, service):
    manager = BatchImporter(service, tmp_path/'rag', tmp_path/'reports')
    manager.save_upload('good.json', json.dumps(document()).encode())
    manager.save_upload('bad.json', b'{')
    first = wait(manager, manager.start()['job_id'])
    revision = service.store.get('DOC_A')['active_revision']
    second = wait(manager, manager.start()['job_id'])
    assert second['skipped'] == 1 and second['failed'] == 1
    assert service.store.get('DOC_A')['active_revision'] == revision
    manager.save_upload('bad.json', json.dumps(document('REPAIRED')).encode())
    repaired = wait(manager, manager.start('files', [{'filename': 'bad.json'}])['job_id'])
    assert repaired['total'] == repaired['completed'] == 1
    assert service.store.get('REPAIRED') and len(service.store.documents()) == 2
    assert first['failed'] == 1
    manager.close()


@pytest.mark.parametrize('mode', ['validate', 'dry_run'])
def test_preview_and_validate_do_not_write_database(tmp_path, service, mode):
    manager = BatchImporter(service, tmp_path/'rag', tmp_path/'reports')
    manager.save_upload('a.json', json.dumps(document()).encode())
    job = wait(manager, manager.start(mode=mode)['job_id'])
    assert job['completed'] == 1 and not service.store.documents()
    assert job['items'][0]['result_status'] == ('valid' if mode == 'validate' else 'dry_run')
    manager.close()


def test_duplicate_normalized_document_id_rejected_without_overwriting_first(tmp_path, service):
    manager = BatchImporter(service, tmp_path/'rag', tmp_path/'reports')
    manager.save_upload('a.json', json.dumps(document('D', 'Nguồn đầu.')).encode())
    manager.save_upload('b.json', json.dumps(document(' D ', 'Nguồn thứ hai.')).encode())
    job = wait(manager, manager.start()['job_id'])
    assert job['completed'] == job['failed'] == 1
    assert 'trùng' in job['items'][1]['error']
    source = service.store.source(service.store.get('D')['active_revision'])
    assert source['document']['sections'][0]['paragraphs'][0]['sentences'][0]['text'] == 'Nguồn đầu.'
    manager.close()


@pytest.mark.parametrize('filename', ['../a.json', '/a.json', 'a\\b.json', 'C:a.json', 'NUL.json', 'COM1.json', 'a.json.', 'a.txt', 'a\x00.json'])
def test_unsafe_upload_names_rejected(filename):
    with pytest.raises(ValueError):
        safe_name(filename)


def test_missing_oversized_symlink_and_upload_error_do_not_stop_valid_files(tmp_path, service):
    manager = BatchImporter(service, tmp_path/'rag', tmp_path/'reports')
    (manager.input_dir/'big.json').write_bytes(b' '*(MAX_BYTES+1))
    save(tmp_path/'outside.json', document('OUTSIDE'))
    (manager.input_dir/'link.json').symlink_to(tmp_path/'outside.json')
    manager.save_upload('ok.json', json.dumps(document()).encode())
    job = wait(manager, manager.start('files', [{'filename': 'missing.json'}, {'filename': 'big.json'},
        {'filename': 'link.json'}, {'filename': 'upload.json', 'upload_error': 'File quá lớn'},
        {'filename': '../outside.json'}, {'filename': 'ok.json'}])['job_id'])
    assert job['failed'] == 5 and job['completed'] == 1
    assert not service.store.get('OUTSIDE')
    assert job['items'][3]['stage'] == 'upload'
    with pytest.raises(ValueError):
        manager.save_upload('big.json', b' '*(MAX_BYTES+1))
    manager.close()


def test_database_failure_retains_active_revision_and_continues(tmp_path, service, monkeypatch):
    service.import_data(document())
    revision = service.store.get('DOC_A')['active_revision']
    stage = service.store.stage
    def fail_one(meta, source, records):
        if meta['document_id'] == 'DOC_A':
            raise RuntimeError('Secret connection details must not enter report')
        stage(meta, source, records)
    monkeypatch.setattr(service.store, 'stage', fail_one)
    manager = BatchImporter(service, tmp_path/'rag', tmp_path/'reports')
    manager.save_upload('a.json', json.dumps(document(text='Nội dung thay đổi.')).encode())
    manager.save_upload('b.json', json.dumps(document('DOC_B')).encode())
    job = wait(manager, manager.start()['job_id'])
    assert job['completed'] == job['failed'] == 1
    assert 'Secret' not in job['items'][0]['error']
    assert service.store.get('DOC_A')['active_revision'] == revision and service.store.get('DOC_B')
    manager.close()


def test_only_one_job_progress_nonblocking_and_shutdown_interrupts_pending(tmp_path, service, monkeypatch):
    entered, release = Event(), Event()
    original = service.import_data
    def blocked(raw, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(raw, **kwargs)
    monkeypatch.setattr(service, 'import_data', blocked)
    manager = BatchImporter(service, tmp_path/'rag', tmp_path/'reports')
    for name in ['a.json', 'b.json']:
        manager.save_upload(name, json.dumps(document(name)).encode())
    job = manager.start()
    try:
        assert entered.wait(2)
        assert manager.get(job['job_id'])['current_file'] == 'a.json'
        assert manager.list()['active_job_id'] == job['job_id']
        with pytest.raises(BatchBusy):
            manager.start()
        with pytest.raises(BatchBusy):
            manager.save_upload('x.json', b'{}')
        manager.stop.set()
    finally:
        release.set()
        manager.close()
    final = manager.get(job['job_id'])
    assert final['status'] == 'interrupted' and final['processed'] == 1
    assert final['items'][1]['status'] == 'pending'
    restored = BatchImporter(service, tmp_path/'rag', tmp_path/'reports')
    assert restored.get(job['job_id']) == final and restored.list()['active_job_id'] is None
    restored.close()


def test_stale_running_job_marked_interrupted_without_loading_input(tmp_path, service):
    manager = BatchImporter(service, tmp_path/'rag', tmp_path/'reports')
    manager.save_upload('a.json', json.dumps(document()).encode())
    job = wait(manager, manager.start()['job_id'])
    manager.close()
    job['status'] = 'running'
    job['finished_at'] = None
    manager.report(job['job_id'], 'json').write_text(json.dumps(job))
    restored = BatchImporter(service, tmp_path/'rag', tmp_path/'reports')
    assert restored.get(job['job_id'])['status'] == 'interrupted'
    assert len(service.store.documents()) == 1 and restored.active is None
    restored.close()


def test_api_upload_import_and_download_reports_with_no_automatic_import(tmp_path, service):
    root = tmp_path/'rag'
    save(root/'already-there.json', document())
    with TestClient(create_app(service, root, tmp_path/'reports')) as client:
        prefix = '/api/v1/rag/batch'
        assert client.get(prefix+'/jobs').json()['items'] == []
        assert not service.store.documents()
        assert client.put(prefix+'/uploads/fixed.json', content=json.dumps(document('B')).encode()).json()['saved']
        assert client.put(prefix+'/uploads/NUL.json', content=b'{}').status_code == 422
        assert client.put(prefix+'/uploads/big.json', content=b' '*(MAX_BYTES+1)).status_code == 413
        assert not (root/'big.json').exists()
        response = client.post(prefix+'/jobs', json={'source': 'files', 'files': [{'filename': 'fixed.json'}]})
        assert response.status_code == 202
        job_id = response.json()['job_id']
        job = wait(client.app.state.batch, job_id)
        assert job['completed'] == 1 and not service.store.get('DOC_A')
        for kind in ['json', 'csv', 'errors']:
            report = client.get(prefix+f'/jobs/{job_id}/report?kind={kind}')
            assert report.status_code == 200 and 'attachment' in report.headers['content-disposition']
        assert client.get(prefix+'/jobs/not-a-job').status_code == 404
        assert client.get(prefix+f'/jobs/{job_id}/report?kind=unknown').status_code == 422
        assert client.post(prefix+'/jobs', json={'source': 'files', 'files': []}).status_code == 422
        assert client.post(prefix+'/jobs', json={'source': 'files', 'files': [{'filename': 'A.json'}, {'filename': 'a.JSON'}]}).status_code == 422


def test_csv_report_neutralizes_spreadsheet_formulas(tmp_path, service):
    manager = BatchImporter(service, tmp_path/'rag', tmp_path/'reports')
    manager.save_upload('=formula.json', json.dumps(document('=formula')).encode())
    job = wait(manager, manager.start()['job_id'])
    csv = manager.report(job['job_id'], 'csv').read_text(encoding='utf-8-sig')
    assert "'=formula.json,'=formula" in csv
    manager.close()


def test_cli_submits_selected_files_and_downloads_reports_with_failure_exit(tmp_path, monkeypatch):
    import httpx
    from scripts.rag import import_folder
    requested = []
    job = {'job_id': 'CLI', 'total': 2, 'processed': 2, 'completed': 1, 'skipped': 0,
           'failed': 1, 'current_file': None, 'status': 'completed'}
    def handle(request):
        requested.append(request)
        if request.method == 'POST':
            assert json.loads(request.content) == {'source': 'files', 'mode': 'commit',
                'files': [{'filename': 'a.json'}, {'filename': 'nested/b.json'}]}
            return httpx.Response(202, json=job)
        if '/report' in request.url.path:
            return httpx.Response(200, content=b'report')
        return httpx.Response(200, json=job)
    client_class = httpx.Client
    monkeypatch.setattr(import_folder.httpx, 'Client', lambda **kwargs: client_class(transport=httpx.MockTransport(handle), **kwargs))
    assert import_folder.main(['--file', 'a.json', '--file', 'nested/b.json', '--reports-dir', str(tmp_path)]) == 1
    assert len(requested) == 5
    assert requested[0].url.path == '/modules/rag/api/v1/rag/batch/jobs'
    assert {path.name for path in tmp_path.iterdir()} == {'CLI.json', 'CLI.csv', 'CLI.errors.csv'}
