import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from hypothesis import given, settings, strategies as st

from watcher.ports import ModelServer
from watcher.servers import OpenAIServer


class _Fake:
    def __init__(self, ids, status=200, body=None):
        outer = self
        self.headers = []
        self.paths = []
        payload = body if body is not None else json.dumps({"data": [{"id": i} for i in ids]}).encode()

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.headers.append(self.headers.get("Authorization"))
                outer.paths.append(self.path)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def test_AC1_present_and_absent():
    f = _Fake(["m"])
    try:
        s = OpenAIServer(url=f.url)
        assert s.ensure_model("m") is True
        assert s.ensure_model("x") is False
        assert f.paths[0] == "/v1/models"
    finally:
        f.close()


@settings(max_examples=25, deadline=None)
@given(ids=st.lists(st.text(min_size=1, max_size=8), max_size=5), n=st.text(min_size=1, max_size=8))
def test_AC1_property_membership(ids, n):
    f = _Fake(ids)
    try:
        assert OpenAIServer(url=f.url).ensure_model(n) is (n in ids)
    finally:
        f.close()


def test_AC1_non_200_and_bad_json_are_false():
    f = _Fake(["m"], status=500)
    g = _Fake([], body=b"not json")
    try:
        assert OpenAIServer(url=f.url).ensure_model("m") is False
        assert OpenAIServer(url=g.url).ensure_model("m") is False
    finally:
        f.close()
        g.close()


def test_AC2_refused_connection():
    f = _Fake([])
    url = f.url
    f.close()
    assert OpenAIServer(url=url, timeout=2).ensure_model("m") is False


def test_AC3_bearer_header_sent(monkeypatch):
    monkeypatch.setenv("K", "secret")
    f = _Fake(["m"])
    try:
        OpenAIServer(url=f.url, api_key_env="K").ensure_model("m")
        assert f.headers == ["Bearer secret"]
    finally:
        f.close()


def test_AC3_no_header_without_env(monkeypatch):
    monkeypatch.delenv("K", raising=False)
    f = _Fake(["m"])
    g = _Fake(["m"])
    try:
        OpenAIServer(url=f.url, api_key_env="K").ensure_model("m")
        OpenAIServer(url=g.url).ensure_model("m")
        assert f.headers == [None]
        assert g.headers == [None]
    finally:
        f.close()
        g.close()


def test_AC4_is_model_server():
    assert isinstance(OpenAIServer(), ModelServer)
