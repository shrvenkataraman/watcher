import json
import os
import urllib.request


class OpenAIServer:
    def __init__(self, url: str = "http://127.0.0.1:8000", api_key_env: str = "", timeout: float = 60, **_):
        self.url = url.rstrip("/")
        self.api_key_env = api_key_env
        self.timeout = timeout

    def ensure_model(self, name: str) -> bool:
        req = urllib.request.Request(f"{self.url}/v1/models")
        key = os.environ.get(self.api_key_env, "") if self.api_key_env else ""
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    return False
                data = json.load(resp)["data"]
                return any(isinstance(m, dict) and m.get("id") == name for m in data)
        except (OSError, ValueError, KeyError, TypeError):
            return False
