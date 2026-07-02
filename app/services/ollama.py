"""Detects whether a local Ollama server is reachable, and whether/how to pull a model."""

import json
import os
import shutil
import subprocess
import urllib.request

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5vl:7b"
DOWNLOAD_URL = "https://ollama.com/download"


def is_available(host=DEFAULT_HOST, timeout=1.5):
    try:
        urllib.request.urlopen(f"{host}/api/tags", timeout=timeout)
        return True
    except Exception:
        return False


def list_models(host=DEFAULT_HOST, timeout=3):
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=timeout) as r:
            data = json.loads(r.read().decode())
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def has_model(model=DEFAULT_MODEL, host=DEFAULT_HOST):
    return model in list_models(host)


def ollama_bin():
    """Path to the ollama CLI: PATH first, then common Windows install locations."""
    found = shutil.which("ollama")
    if found:
        return found
    for c in _install_candidates():
        if os.path.exists(c):
            return c
    return "ollama"


def _install_candidates():
    return [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
        r"C:\Program Files\Ollama\ollama.exe",
    ]


def is_installed():
    """Whether the ollama CLI is present at all, regardless of whether the server is running."""
    if shutil.which("ollama"):
        return True
    return any(os.path.exists(c) for c in _install_candidates())


def pull_model(model=DEFAULT_MODEL, timeout=1800):
    """Runs `ollama pull <model>` to completion. Returns True on success."""
    try:
        result = subprocess.run(
            [ollama_bin(), "pull", model], capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode == 0
    except Exception:
        return False
