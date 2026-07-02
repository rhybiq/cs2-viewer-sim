"""Detects whether a local Ollama server is reachable."""

import urllib.request

DEFAULT_HOST = "http://localhost:11434"


def is_available(host=DEFAULT_HOST, timeout=1.5):
    try:
        urllib.request.urlopen(f"{host}/api/tags", timeout=timeout)
        return True
    except Exception:
        return False
