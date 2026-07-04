"""Detects whether the optional faster-whisper dependency (speech-to-text) is installed."""


def is_available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False
