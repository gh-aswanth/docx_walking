"""Vercel entry point.

The Python runtime looks for a module under ``api/`` exporting an ASGI ``app``.
Everything real lives in :mod:`docx_redline.web`; this only puts the repository
root on the path, since the deploy runs from a checkout rather than an install.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docx_redline.web.main import app  # noqa: E402

__all__ = ["app"]
