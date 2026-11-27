"""Offline tests for the optional local GPT-4chan preview."""
import io
import json
import unittest
from unittest.mock import patch, Mock
from urllib.error import URLError
from persona_responder import generate_gpt4chan_preview
from persona_responder_ui import PersonaResponderMixin


class GPT4chanPreviewTests(unittest.TestCase):
    @patch('persona_responder.request.build_opener')
    def test_local_completion(self, opener):
        opener.return_value.open.return_value = io.BytesIO(
            json.dumps({'choices':[{'text':'hello there'}]}).encode())
        self.assertEqual(generate_gpt4chan_preview('sample'), 'hello there')
        req = opener.return_value.open.call_args.args[0]
        self.assertEqual(req.full_url, 'http://127.0.0.1:5000/v1/completions')
        self.assertEqual(json.loads(req.data)['model'], 'gpt4chan')
        self.assertEqual(json.loads(req.data)['prompt'], 'sample\n')
        self.assertIsNone(req.get_header('Authorization'))

    @patch('persona_responder.request.build_opener')
    def test_unavailable(self, opener):
        opener.return_value.open.side_effect = URLError('offline')
        with self.assertRaisesRegex(RuntimeError, 'backend unavailable'):
            generate_gpt4chan_preview('sample')

    @patch('persona_responder.request.build_opener')
    def test_empty_and_oversize_do_not_request(self, opener):
        for value in ('', 'x'*501):
            with self.assertRaises(ValueError):
                generate_gpt4chan_preview(value)
        opener.assert_not_called()

    @patch('persona_responder_ui.generate_gpt4chan_preview')
    def test_worker_cannot_generate_live_gpt4chan(self, generate):
        app=Mock()
        PersonaResponderMixin._responder_worker(
            app, {'sample':'hello'}, 'gpt4chan', 1, False, True)
        generate.assert_not_called()
        self.assertIn('preview only', app._responder_results.put.call_args.args[0][2])

    def test_send_is_blocked_in_preview(self):
        app=Mock()
        app.responder_gpt4chan_var.get.return_value=True
        self.assertIn('preview only', PersonaResponderMixin._responder_send(app,'hello'))

    @patch('persona_responder_ui.generate_persona_reply')
    def test_standard_worker_unchanged(self, generate):
        app=Mock()
        generate.return_value='hello'
        payload={'target':'test'}
        PersonaResponderMixin._responder_worker(app,payload,'gpt-5-mini',1)
        generate.assert_called_once_with(payload,model='gpt-5-mini')
        app._responder_results.put.assert_called_once_with((1,'hello',None,False))
