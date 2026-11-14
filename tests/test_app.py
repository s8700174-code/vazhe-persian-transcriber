import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import sys

from fastapi.testclient import TestClient
import app


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        app.jobs.clear()
        app.model_cache.clear()
        self.headers = {"X-V2T-Client": "local"}

    def test_home_and_health(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertTrue(self.client.get('/api/health').json()['local'])

    def test_block_cross_origin_and_missing_header(self):
        self.assertEqual(self.client.post('/api/jobs').status_code, 403)
        self.assertEqual(self.client.post('/api/jobs', headers={**self.headers, 'Origin': 'https://evil.example'}).status_code, 403)

    def test_size_limit_and_oversized_request(self):
        self.assertEqual(self.client.get('/api/health').json()['max_bytes'], 10 * 1024**3)
        response = self.client.post('/api/jobs', headers={**self.headers, 'Content-Length': str(app.MAX_BYTES + 2 * 1024**2)})
        self.assertEqual(response.status_code, 413)
        self.assertIn('۱۰', response.json()['detail'])

    def test_stream_limit_cleanup(self):
        with patch.object(app, 'MAX_BYTES', 4), patch.object(app.worker, 'submit') as submit:
            response = self.client.post('/api/jobs', headers=self.headers, files={'file': ('voice.wav', b'12345')})
            self.assertEqual(response.status_code, 413)
            submit.assert_not_called()
            self.assertEqual(app.jobs, {})

    def test_invalid_and_empty_upload(self):
        for filename, content in [('test.exe', b'x'), ('empty.wav', b'')]:
            response = self.client.post('/api/jobs', headers=self.headers, files={'file': (filename, content)})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(len(app.jobs), 0)

    def test_queue_cancel_and_busy(self):
        with patch.object(app.worker, 'submit') as submit:
            response = self.client.post('/api/jobs', headers=self.headers, files={'file': ('voice.wav', b'audio')})
            self.assertEqual(response.status_code, 202)
            job_id = response.json()['id']
            path = submit.call_args.args[2]
            try:
                again = self.client.post('/api/jobs', headers=self.headers, files={'file': ('voice.wav', b'audio')})
                self.assertEqual(again.status_code, 409)
                self.client.delete(f'/api/jobs/{job_id}', headers=self.headers)
                self.assertTrue(self.client.get(f'/api/jobs/{job_id}').json()['cancel_requested'])
            finally:
                Path(path).unlink(missing_ok=True)

    def test_transcription_pipeline_and_cleanup(self):
        segment = SimpleNamespace(start=0, end=1.5, text=' يك صدا ', avg_logprob=-1, no_speech_prob=.1)
        class Model:
            def __init__(self, *args, **kwargs): pass
            def transcribe(self, path, **kwargs):
                assert kwargs['language'] == 'fa'
                assert kwargs['task'] == 'transcribe'
                return iter([segment]), SimpleNamespace(duration=2)
        with tempfile.NamedTemporaryFile(delete=False) as stream:
            path = stream.name
        app.jobs['test'] = {'cancel_requested': False, 'segments': []}
        with patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(WhisperModel=Model)}):
            app.run_transcription('test', path, 'large-v3', 'cpu', '', True)
        self.assertFalse(Path(path).exists())
        self.assertEqual(app.jobs['test']['status'], 'done')
        self.assertEqual(app.jobs['test']['segments'][0]['text'], 'یک صدا')
        self.assertTrue(app.jobs['test']['segments'][0]['review'])

    def test_model_error_cleans_up(self):
        with tempfile.NamedTemporaryFile(delete=False) as stream:
            path = stream.name
        app.jobs['test'] = {'cancel_requested': False, 'segments': []}
        with patch.dict(sys.modules, {'faster_whisper': None}), self.assertLogs('v2t', level='ERROR'):
            app.run_transcription('test', path, 'large-v3', 'cpu', '', True)
        self.assertEqual(app.jobs['test']['status'], 'error')
        self.assertFalse(Path(path).exists())


if __name__ == '__main__':
    unittest.main()
