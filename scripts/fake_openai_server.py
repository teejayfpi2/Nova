"""A tiny OpenAI-compatible stub server for offline smoke tests.

It answers /v1/chat/completions and drives one tool call so the full agent loop
(tool dispatch, memory write, follow-up answer) can be exercised without a real
model. Start it with:

    python scripts/fake_openai_server.py 9099
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

SCRIPT: list[dict] = [
    {
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "remember", "arguments": json.dumps({"key": "user_name", "value": "Sam"})},
            }
        ],
    },
    {"content": "Nice to meet you, Sam. I'll remember that.", "tool_calls": []},
]

# Used when the user's message mentions "type": drives a real device tool call so
# the remote-bridge round trip can be exercised end to end.
DEVICE_SCRIPT: list[dict] = [
    {
        "content": "",
        "tool_calls": [
            {
                "id": "call_dev",
                "type": "function",
                "function": {
                    "name": "type_text",
                    "arguments": json.dumps({"text": "hello from nova", "target": "phone"}),
                },
            }
        ],
    },
    {"content": "Typed it on your phone.", "tool_calls": []},
]


class Handler(BaseHTTPRequestHandler):
    turn = 0

    def log_message(self, *args):  # silence
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        if self.path.endswith("/chat/completions"):
            messages = body.get("messages", [])
            last_user = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    last_user = (m.get("content") or "")
                    break
            script = DEVICE_SCRIPT if "type" in last_user.lower() else SCRIPT
            has_tool_result = any(m.get("role") == "tool" for m in messages)
            message = script[1] if has_tool_result else script[0]
            payload = {
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "model": body.get("model", "fake"),
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            }
            self._send(200, payload)
        else:
            self._send(404, {"error": "not found"})

    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9099
    print(f"fake OpenAI server on http://127.0.0.1:{port}/v1", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
