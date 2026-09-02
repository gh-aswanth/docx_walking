"""Discover the example scripts, run them, and collect what they produced.

Each example is executed in a subprocess with ``DOCX_REDLINE_OUT`` pointed at a
scratch directory, so nothing is written into the repository and the same code
works on a read-only serverless filesystem.

Running them for real rather than shipping canned output is the point: the demo
shows what the library does *now*, and an example that breaks shows up here
exactly as it would in CI.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Installed from a wheel, the examples ship *inside* the package. Running from a
# checkout they are at the repository root, where the tests and CI expect them.
# Prefer the shipped copy so an installed `docx-redline[web]` is self-contained.
_SHIPPED = HERE / "examples"
_REPO = HERE.parent.parent / "examples"
EXAMPLES = _SHIPPED if (_SHIPPED / "_shared.py").exists() else _REPO
ROOT = EXAMPLES.parent

#: Which layer each example belongs to, mirroring examples/README.md.
GROUPS = [
    ("Layer 1 · Redliner", range(1, 11), "Targeted, scripted edits: you know the paragraph."),
    (
        "Layer 2 · ParagraphIndex",
        range(11, 17),
        "Stable paragraph ids and quoted spans, verified before anything is written.",
    ),
    (
        "Layer 3 · Action items",
        range(17, 22),
        "A model restructures the document; numbering and references follow.",
    ),
    ("Other surfaces", range(22, 27), "Compare, op plans, structure, the CLI, errors."),
]


@dataclass
class Example:
    number: int
    slug: str  # "01_quickstart"
    path: Path
    title: str  # "Quickstart — the smallest useful redline"
    summary: str  # the rest of the docstring
    source: str

    @property
    def name(self) -> str:
        return self.slug.split("_", 1)[1].replace("_", " ")


@dataclass
class Run:
    stdout: str
    stderr: str
    ok: bool
    seconds: float
    documents: list[str] = field(default_factory=list)  # produced .docx filenames
    workdir: Path | None = None


def _docstring(source: str) -> tuple[str, str]:
    try:
        doc = ast.get_docstring(ast.parse(source)) or ""
    except SyntaxError:
        doc = ""
    lines = [line.rstrip() for line in doc.splitlines()]
    title = lines[0] if lines else ""
    title = re.sub(r"^\d+\s*·\s*", "", title).rstrip(".")
    body = "\n".join(lines[1:]).strip()
    return title, body


@lru_cache(maxsize=1)
def catalogue() -> list[Example]:
    out = []
    for path in sorted(EXAMPLES.glob("[0-9][0-9]_*.py")):
        source = path.read_text(encoding="utf-8")
        title, summary = _docstring(source)
        out.append(
            Example(
                number=int(path.stem[:2]),
                slug=path.stem,
                path=path,
                title=title or path.stem,
                summary=summary,
                source=source,
            )
        )
    return out


def find(slug: str) -> Example | None:
    return next((e for e in catalogue() if e.slug == slug), None)


def grouped() -> list[tuple[str, str, list[Example]]]:
    by_number = {e.number: e for e in catalogue()}
    out = []
    for name, span, blurb in GROUPS:
        members = [by_number[n] for n in span if n in by_number]
        if members:
            out.append((name, blurb, members))
    return out


#: Runs are cached per process. A cold serverless invocation pays for one run;
#: everything after that is free, and the output is deterministic anyway.
_CACHE: dict[str, Run] = {}


def run(example: Example, *, timeout: int = 120) -> Run:
    if example.slug in _CACHE:
        return _CACHE[example.slug]

    workdir = Path(tempfile.mkdtemp(prefix=f"{example.slug}-"))
    env = {
        **os.environ,
        "DOCX_REDLINE_OUT": str(workdir),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(ROOT),
    }
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, str(example.path)],
            cwd=EXAMPLES,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=timeout,
        )
        result = Run(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            ok=proc.returncode == 0,
            seconds=time.perf_counter() - started,
            documents=sorted(p.name for p in workdir.glob("*.docx")),
            workdir=workdir,
        )
    except subprocess.TimeoutExpired:
        result = Run(
            "", f"timed out after {timeout}s", False, time.perf_counter() - started, [], workdir
        )

    _CACHE[example.slug] = result
    return result


def document(example: Example, filename: str) -> Path | None:
    """A .docx this example produced, resolved safely inside its own workdir."""
    result = run(example)
    if not result.workdir:
        return None
    candidate = (result.workdir / filename).resolve()
    if candidate.parent != result.workdir.resolve() or not candidate.exists():
        return None  # no traversal outside the scratch directory
    return candidate
