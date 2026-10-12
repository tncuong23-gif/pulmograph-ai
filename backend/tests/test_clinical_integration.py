import asyncio
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from app import main
from app.services.modules import ModuleClient
from app.services.orchestrator import Orchestrator
from app.storage import ConversationStore


class ClinicalClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_paths_payloads_and_dedicated_timeout(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"ok": True, "data": {"top5": []}})
        real_client = httpx.AsyncClient
        client = ModuleClient(context_url='http://context', clinical_url='http://clinical',
                              kg_url='http://kg', rag_url='http://rag', timeout=45, clinical_timeout=240)
        with patch('app.services.modules.httpx.AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
            await client.clinical_query('test question')
            await client.clinical_analyze_file('record.txt', b'record content', 'text/plain')
            await client.rag_search('q')
        self.assertEqual(json.loads(requests[0].content), {'text': 'test question'})
        self.assertEqual(requests[0].url.path, '/api/v1/ask-symptoms')
        self.assertEqual(requests[1].url.path, '/api/v1/analyze-file')
        self.assertIn(b'name="file"; filename="record.txt"', requests[1].content)
        self.assertEqual([r.extensions['timeout']['read'] for r in requests], [240, 240, 45])

    def test_invalid_clinical_payload_not_success(self):
        for result in ({'ok': False, 'data': {'x': 1}}, {'ok': True, 'data': None},
                       {'ok': True, 'data': {'raw_output_file': 'bad json'}}):
            with self.assertRaises(ValueError): ModuleClient._validate_clinical(result)
        self.assertEqual(ModuleClient._validate_clinical({'ok': True, 'data': {'top5': []}})['ok'], True)

    async def test_diagnostic_chat_cannot_bypass_confirmation_with_cached_record(self):
        classifier = unittest.mock.Mock()
        classifier.predict.return_value = {'label': 'DIAGNOSTIC_ASSESSMENT'}
        modules = AsyncMock()
        modules.context_resolve.return_value = {'normalized_question': 'q'}
        modules.clinical_query.return_value = {'ok': True, 'data': {'top5': []}}
        llm = AsyncMock(); llm.generate.return_value = 'answer'
        orch = Orchestrator(classifier, modules, llm)
        orch.attachment_lookup = lambda _: {'status': 'processed', 'analysis_json': json.dumps({'ok': True, 'data': {'case': 'stored'}})}
        await orch.answer(conversation_id='c', message_id='m', question='q', timestamp='t',
                          attachments=[{'type': 'medical_record', 'serverId': 'f', 'analysis_json': 'UNTRUSTED'}])
        modules.clinical_analyze_file.assert_not_called()
        llm.generate.assert_not_awaited()
        modules.clinical_query.assert_not_awaited()


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patch = patch.object(main, 'settings', replace(main.settings, database_path=root/'db.sqlite', upload_dir=root/'uploads'))
        self.patch.start()
        self.client = TestClient(main.app).__enter__()
        self.fake = AsyncMock()
        self.fake.clinical_analyze_file.return_value = {'ok': True, 'data': {'entities': []}}
        main.app.state.modules = self.fake
        self.fake_llm = AsyncMock()
        self.fake_llm.generate.return_value = 'Tóm tắt bệnh án kiểm thử.'
        main.app.state.llm = self.fake_llm

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.patch.stop();self.tmp.cleanup()

    def upload(self):
        return self.client.post('/api/v1/files/medical-record', data={'clientId': 'client-file'}, files={'file': ('record.txt', b'fixture', 'text/plain')})

    def test_upload_calls_clinical_and_status_tracks_result(self):
        response = self.upload()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['status'], 'processing')
        fid = response.json()['serverId']
        status = self.client.get('/api/v1/files/'+fid).json()
        self.assertEqual(status['status'], 'processed')
        self.fake.clinical_analyze_file.assert_awaited_once_with('record.txt', b'fixture', 'text/plain')
        self.fake_llm.generate.assert_awaited_once()
        self.assertEqual(self.fake_llm.generate.call_args.args[1]['route'], 'MEDICAL_RECORD_ANALYSIS')
        self.assertEqual(status['analysisAnswer'], 'Tóm tắt bệnh án kiểm thử.')
        stored = main.app.state.store.get_attachment(fid)
        self.assertEqual(json.loads(stored['analysis_json'])['data'], {'entities': []})
        self.assertNotIn('analysis_json', status)

    def test_file_message_is_rejected_before_classifier_path(self):
        main.app.state.orchestrator.answer = AsyncMock(side_effect=AssertionError('classifier path called'))
        response = self.client.post('/api/v1/chat/message', json={
            'conversationId': 'c',
            'message': {
                'id': 'm', 'role': 'user', 'content': 'Tôi bị bệnh gì?',
                'attachments': [{'id': 'f', 'serverId': 'f', 'type': 'medical_record',
                                'fileName': 'record.txt', 'fileSize': 3}],
            },
        })
        self.assertEqual(response.status_code, 422)
        main.app.state.orchestrator.answer.assert_not_awaited()

    def test_upstream_timeout_is_error_not_processed(self):
        self.fake.clinical_analyze_file.side_effect = httpx.ReadTimeout('slow')
        response = self.upload()
        status = self.client.get('/api/v1/files/'+response.json()['serverId']).json()
        self.assertEqual(status['status'], 'error')
        self.assertIn('thời gian', status['error'])

    def test_empty_upload_not_analyzed(self):
        response = self.client.post('/api/v1/files/medical-record', data={'clientId': 'c'}, files={'file': ('r.txt', b'', 'text/plain')})
        self.assertEqual(response.status_code, 422)
        self.fake.clinical_analyze_file.assert_not_called()

    def test_migration_and_restart_keep_results(self):
        response = self.upload(); fid=response.json()['serverId']
        store = ConversationStore(main.settings.database_path)
        store.mark_interrupted_uploads()
        self.assertEqual(store.get_attachment(fid)['status'], 'processed')
        store.set_attachment_analysis(fid, 'processing')
        store.mark_interrupted_uploads()
        self.assertEqual(store.get_attachment(fid)['status'], 'error')
