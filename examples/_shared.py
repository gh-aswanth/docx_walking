"""Shared scaffolding for the examples. Not part of the library.

Every example is standalone: run it directly, or run them all with
``python examples/run_all.py``. Each writes its output under
``examples/output/`` so nothing lands in the repo root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# These examples print the characters this library exists to normalise: smart
# quotes, en dashes, U+2212 MINUS. A Windows console defaults stdout to cp1252,
# which cannot encode them, so an example would die on its own output rather
# than on anything to do with redlining. Ask for UTF-8 explicitly.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

#: Environment for any example that shells out, so the child agrees.
CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = Path(__file__).resolve().parent / "data"
SOURCE = DATA / "Sample_Software_License_Agreement.docx"
PLAN = DATA / "action_items.json"
# Overridable so the examples can run somewhere writable -- a serverless
# filesystem is read-only apart from /tmp, and the web demo runs each example
# into a scratch directory rather than the repo.
OUT = Path(os.environ.get("DOCX_REDLINE_OUT") or Path(__file__).resolve().parent / "output")
OUT.mkdir(parents=True, exist_ok=True)

AUTHOR = "Outside Counsel"


def banner(title: str) -> None:
    print("=" * 76)
    print(title)
    print("=" * 76)


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def fresh(**kwargs):
    """A Redliner over an untouched copy of the sample contract."""
    from docx_redline import Redliner

    kwargs.setdefault("author", AUTHOR)
    return Redliner(SOURCE, **kwargs)


def save(rl, name: str) -> Path:
    path = OUT / name
    rl.save(path)
    # OUT is overridable, so it is not always inside the repo -- print a
    # relative path when it is, and the full one when it is not.
    try:
        shown = path.relative_to(ROOT)
    except ValueError:
        shown = path
    print(f"\nwrote {shown}")
    return path


def show(rl, limit: int = 0) -> None:
    print(rl.summary().format(limit=limit))
