# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""TPC controlled provider: exact malformed/valid content, real deployed executor.

Run: python test-e2e/infra/automation/d3/think_prefix_mock_server.py --port 19091
This fixture never contacts an external model and records no credentials.
"""
import argparse
import json
import uuid
import sys
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from test.common.openai_compatible_mock_server import MockState, OpenAICompatibleMockHandler


class Handler(OpenAICompatibleMockHandler):
    def do_GET(self):
        if urlsplit(self.path).path == '/__stats' and getattr(self.server, 'observation_marker', None):
            self._send_json(200, {**self.state.snapshot(), 'observation_counts': self.server.observation_counts})
        else:
            super().do_GET()

    def do_POST(self):
        payload = self._read_json()
        path = urlsplit(self.path).path
        if path == '/__control':
            responses = payload.get('responses', [])
            if not responses or not all(isinstance(item, str) for item in responses):
                self._send_error(400, 'invalid_request_error', 'responses must be nonempty strings')
                return
            marker = payload.get('observation_marker')
            if marker is not None and (not isinstance(marker, str) or not 1 <= len(marker) <= 256):
                self._send_error(400, 'invalid_request_error', 'Invalid observation marker')
                return
            self.server.observation_marker = marker
            self.server.observation_counts = []
            self.state.configure({})
            self.server.responses = responses
            self.server.finish_reason = payload.get('finish_reason', 'stop')
            self.server.auxiliary_title = payload.get('auxiliary_title', 'TPC verification')
            self._send_json(200, self.state.snapshot())
            return
        if path not in {'/v1/chat/completions', '/chat/completions'}:
            self._send_error(404, 'not_found', 'Unknown endpoint')
            return
        # UI title generation has a separate reserve and must not consume an
        # Agent response. Agent fixture reserve is fixed at 4096.
        if payload.get('max_tokens') != 4096:
            text = self.server.auxiliary_title
            finish = 'stop'
        else:
            number, _ = self.state.record(payload, bool(self.headers.get('Authorization')))
            if getattr(self.server, 'observation_marker', None):
                self.server.observation_counts.append(json.dumps(payload.get('messages', []), ensure_ascii=False).count(self.server.observation_marker))
            text = self.server.responses[min(number - 1, len(self.server.responses) - 1)]
            finish = self.server.finish_reason
        if payload.get('stream'):
            ident = 'chatcmpl-tpc-' + uuid.uuid4().hex
            chunks = [self._completion_chunk(request_id=ident, model=payload['model'],
                        delta={'content': text[i:i + 8]}, finish_reason=None)
                      for i in range(0, len(text), 8)]
            chunks.append(self._completion_chunk(request_id=ident, model=payload['model'],
                          delta={}, finish_reason=finish))
            chunks.append(self._completion_chunk(request_id=ident, model=payload['model'], delta={},
                          finish_reason=None, choices=False,
                          usage={'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}))
            self._send_bytes(200, b''.join(chunks) + b'data: [DONE]\n\n', 'text/event-stream')
        else:
            self._send_json(200, {'id': 'tpc', 'object': 'chat.completion', 'model': payload['model'],
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': text},
                             'finish_reason': finish}],
                'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=19091)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('0.0.0.0', args.port), Handler)
    server.mock_state = MockState()
    server.responses = ['<final_answer>TPC ready</final_answer>']
    server.finish_reason = 'stop'
    server.auxiliary_title = 'TPC verification'
    server.serve_forever()
