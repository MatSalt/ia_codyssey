import unittest
from unittest.mock import patch
from tests.test_coach import provider_response
import os
try:
    from api.rewrite import app
except ImportError:
    app = None

class RouteTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(app, 'Implement api.rewrite app')
        self.client = app.test_client()

    def test_post_runs_validation_and_returns_four_levels(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}), patch('services.coach.urlopen', return_value=provider_response()):
            response = self.client.post('/api/rewrite', json={'text': 'Hello'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['results']), 4)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_empty_input_and_invalid_json_are_json_errors(self):
        for kwargs in [{'json': {'text': ''}}, {'data': '{', 'content_type': 'application/json'}, {'json': []}]:
            response = self.client.post('/api/rewrite', **kwargs)
            self.assertEqual(response.status_code, 400)
            self.assertIn('message', response.json['error'])

    def test_wrong_method_and_oversized_body_have_json_errors(self):
        self.assertEqual(self.client.get('/api/rewrite').status_code, 405)
        self.assertIn('error', self.client.get('/api/rewrite').json)
        response = self.client.post('/api/rewrite', data='x' * 25000, content_type='application/json')
        self.assertEqual(response.status_code, 413)
        self.assertIn('error', response.json)

    def test_missing_key_error_is_safe_and_actionable(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post('/api/rewrite', json={'text': 'Hello'})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json['error']['code'], 'NOT_CONFIGURED')

    def test_public_routes_do_not_expose_source_or_environment(self):
        for path in ['/.env.local', '/services/coach.py', '/api/rewrite.py', '/docs/service-plan.md', '/css/../../.env.local']:
            self.assertEqual(self.client.get(path).status_code, 404, path)

if __name__ == '__main__': unittest.main()
