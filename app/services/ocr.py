"""Detects whether the optional EasyOCR dependency (text overlay quality) is installed."""


def is_available():
    try:
        import easyocr  # noqa: F401
        return True
    except ImportError:
        return False
