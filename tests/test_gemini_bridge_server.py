import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from ai_sprints.gemini_bridge_server import BridgeServer, MAX_BODY, extension_id

REVIEW = {
    'verdict': 'approved', 'risk_level': 'low', 'blocking_findings': [],
    'evidence': [{'path': 'example.py', 'line': 1, 'reason': 'Coberto.'}],
    'required_tests': [], 'summary': 'Validado.',
    'rewards': {name: {'delta': 4, 'reason': 'Bom trabalho.'} for name in ('worker_4b', 'reviewer_9b')},
}

class BridgeTests(unittest.TestCase):
    def test_extension_id_accepts_id_or_url_and_rejeita_placeholder(self):
        expected = 'a' * 32
        self.assertEqual(extension_id(expected), expected)
        self.assertEqual(extension_id(f'chrome-extension://{expected}/popup.html'), expected)
        with self.assertRaisesRegex(Exception, 'brave://extensions'):
            extension_id('ID_DA_EXTENSAO')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = BridgeServer(Path(self.tmp.name), 't' * 40, 'a' * 32, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01})
        self.thread.start()
        self.gate = self.server.gate

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, method='GET', path='/gemini/next', body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        fields = {'Authorization': 'Bearer ' + 't' * 40, 'Content-Type': 'application/json'}
        fields.update(headers or {})
        conn.request(method, path, body=None if body is None else json.dumps(body), headers=fields)
        response = conn.getresponse()
        data = response.read()
        status = response.status
        conn.close()
        return status, json.loads(data) if data else None

    def prepare(self, fingerprint='v1', patch='+value=1'):
        path = self.gate.prepare(job_id='sprint_test', fingerprint=fingerprint,
            objective='Extrair funcao', patch=patch, tests='1 passed', qwen_review={})
        return json.loads(path.read_text(encoding='utf-8'))

    def payload(self, job, review=None):
        return {key: job[key] for key in ('job_id', 'fingerprint', 'content_sha256')} | {'response': review or REVIEW}

    def test_http_roundtrip_rewards_and_retry(self):
        job = self.prepare()
        self.assertIn('worker_4b', job['prompt'])
        self.assertEqual(self.request()[1], job)
        payload = self.payload(job)
        self.assertEqual(self.request('POST', '/gemini/result', payload)[0], 200)
        first = self.gate.result_path(job['job_id']).read_bytes()
        self.assertEqual(self.request('POST', '/gemini/result', payload)[0], 200)
        self.assertEqual(first, self.gate.result_path(job['job_id']).read_bytes())
        self.assertTrue(self.gate.approved(self.gate.load_result(job['job_id'], 'v1')))
        self.assertEqual(self.request()[0], 204)

    def test_no_auth_and_foreign_origin_and_host(self):
        self.prepare()
        self.assertEqual(self.request(headers={'Authorization': ''})[0], 401)
        self.assertEqual(self.request(headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request(headers={'Origin': 'chrome-extension://' + 'b' * 32})[0], 403)
        self.assertEqual(self.request(headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request(headers={'Origin': self.server.origin})[0], 200)

    def test_health_and_preflight(self):
        self.assertEqual(self.request(path='/health', headers={'Authorization': ''})[0], 200)
        self.assertEqual(self.request('OPTIONS', headers={'Authorization': '', 'Origin': self.server.origin})[0], 204)

    def test_old_fingerprint_and_same_fingerprint_changed_content(self):
        old = self.prepare()
        self.prepare('v2')
        self.assertEqual(self.request('POST', '/gemini/result', self.payload(old))[0], 409)
        latest = self.prepare('v2')
        self.prepare('v2', '+value=2')
        self.assertEqual(self.request('POST', '/gemini/result', self.payload(latest))[0], 409)
        self.assertFalse(self.gate.result_path('sprint_test').exists())

    def test_conflicting_result_never_overwrites(self):
        job = self.prepare()
        self.request('POST', '/gemini/result', self.payload(job))
        changed = copy.deepcopy(REVIEW)
        changed['summary'] = 'Outro review.'
        self.assertEqual(self.request('POST', '/gemini/result', self.payload(job, changed))[0], 409)
        self.assertEqual(self.gate.load_result('sprint_test', 'v1')['summary'], REVIEW['summary'])

    def test_invalid_rewards_and_missing_rewards(self):
        job = self.prepare()
        for delta in (True, 11, -11, 1.5, '2'):
            invalid = copy.deepcopy(REVIEW)
            invalid['rewards']['worker_4b']['delta'] = delta
            self.assertEqual(self.request('POST', '/gemini/result', self.payload(job, invalid))[0], 400)
        invalid = copy.deepcopy(REVIEW)
        del invalid['rewards']
        self.assertEqual(self.request('POST', '/gemini/result', self.payload(job, invalid))[0], 400)
        self.assertFalse(self.gate.result_path('sprint_test').exists())

    def test_path_traversal_and_unknown_job(self):
        job = self.prepare()
        payload = self.payload(job)
        payload['job_id'] = '../outside'
        self.assertEqual(self.request('POST', '/gemini/result', payload)[0], 400)
        payload['job_id'] = 'not_found'
        self.assertEqual(self.request('POST', '/gemini/result', payload)[0], 404)

    def test_invalid_queue_does_not_block_good_job(self):
        job = self.prepare()
        (self.gate.outbox / 'aaa.json').write_text('{', encoding='utf-8')
        self.assertEqual(self.request()[1], job)

    def test_sensitive_queue_blocked(self):
        job = self.prepare()
        job['prompt'] = 'API_KEY="this-is-a-private-value"'
        self.gate.request_path('sprint_test').write_text(json.dumps(job), encoding='utf-8')
        self.assertEqual(self.request()[0], 204)

    def test_body_size_and_content_type(self):
        self.assertEqual(self.request('POST', '/gemini/result', {}, {'Content-Length': str(MAX_BODY + 1)})[0], 413)
        self.assertEqual(self.request('POST', '/gemini/result', {}, {'Content-Type': 'text/plain'})[0], 415)

    def test_concurrent_duplicate_submissions(self):
        from concurrent.futures import ThreadPoolExecutor
        job = self.prepare()
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(lambda _: self.request('POST', '/gemini/result', self.payload(job))[0], range(4)))
        self.assertEqual(statuses, [200] * 4)

    def test_prepare_invalidates_result_and_fenced_json_is_accepted(self):
        job = self.prepare()
        payload = self.payload(job)
        payload['response'] = '```json\n' + json.dumps(REVIEW) + '\n```'
        self.assertEqual(self.request('POST', '/gemini/result', payload)[0], 200)
        self.prepare('new')
        self.assertIsNone(self.gate.load_result('sprint_test', 'new'))

if __name__ == '__main__':
    unittest.main()
