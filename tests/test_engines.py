import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import app
import engines


class EnginesTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.headers = {'X-V2T-Client':'local'}
        app.jobs.clear()

    def post(self, **values):
        return self.client.post('/api/jobs',headers=self.headers,
            files={'file':('test.wav',b'audio')}, data={'model':'scribe-v2',**values})

    def test_cloud_consent_and_key_required(self):
        with patch.object(app.worker,'submit') as worker:
            self.assertEqual(self.post(api_key='test').status_code,400)
            self.assertEqual(self.post(cloud_consent='true').status_code,400)
            worker.assert_not_called()

    def test_key_not_in_job_response(self):
        with patch.object(app.worker,'submit') as worker:
            response = self.post(api_key='test-secret',cloud_consent='true')
            self.assertEqual(response.status_code,202)
            path = worker.call_args.args[2]
            try:
                data = self.client.get('/api/jobs/'+response.json()['id']).text
                self.assertNotIn('test-secret',data)
                self.assertNotIn('api_key',data)
            finally:
                Path(path).unlink()

    def test_persian_not_ready(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(engines,'PERSIAN_MODEL',Path(directory)):
            with self.assertRaises(engines.EngineError):
                engines.local_model_name('persian-v4')

    def test_speaker_boundaries_and_timestamps(self):
        result = engines.scribe_segments({'words':[
            {'type':'word','text':'سلام','start':1,'end':2,'speaker_id':'speaker_0'},
            {'type':'spacing','text':' '},
            {'type':'word','text':'خوبید؟','start':2,'end':3,'speaker_id':'speaker_0'},
            {'type':'word','text':'بله','start':4,'end':5,'speaker_id':'speaker_1'}]})
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['text'],'سلام خوبید؟')
        self.assertEqual(result[1]['start'],4)
        self.assertEqual(result[1]['speaker'],'speaker_1')

    def test_zero_retention_and_no_retry(self):
        client = MagicMock()
        client.post.return_value.status_code = 403
        with tempfile.TemporaryDirectory() as directory, patch.object(engines.httpx,'Client') as factory:
            path = Path(directory) / 'test.wav'
            path.write_bytes(b'audio')
            factory.return_value.__enter__.return_value = client
            with self.assertRaises(engines.EngineError):
                engines.transcribe_scribe(str(path),'secret',True,lambda:False)
            self.assertEqual(client.post.call_count,1)
            self.assertEqual(client.post.call_args.kwargs['params'],{'enable_logging':'false'})

    def test_scribe_success_and_cleanup(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path=f.name
        app.jobs['cloud']={'cancel_requested':False,'segments':[]}
        with patch.object(app,'transcribe_scribe',return_value=[{'start':0,'end':2,'text':'يك','review':False}]):
            app.run_transcription('cloud',path,'scribe-v2','cpu','',True,'secret')
        self.assertEqual(app.jobs['cloud']['status'],'done')
        self.assertEqual(app.jobs['cloud']['segments'][0]['text'],'یک')
        self.assertFalse(Path(path).exists())
