"""Structural checks on the markdown, fast enough for a pre-commit hook.

    uv run python scripts/check_docs.py
    uv run python scripts/check_docs.py --mermaid   # + parse every diagram for real

The plain run needs nothing but Python. `--mermaid` shells out to mermaid-cli
via npx, which is thorough but slow, so it is opt-in rather than part of the
gate.

What it catches, in the order these have actually gone wrong here:

1. A mermaid node label delimited with single quotes. Mermaid wants
   ``id["label"]``; ``id['label']`` is a parse error that renders as a red box
   on GitHub and nowhere else, so it survives review.
2. An unbalanced code fence, which silently swallows the rest of the file.
3. A link to a file that has been moved or deleted.
4. A module path from before the package was split into subpackages.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [
    *sorted(ROOT.glob("docs/*.md")),
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "examples" / "README.md",
    ROOT / "examples" / "data" / "README.md",
]

#: Modules that moved when the package was split. A bare `x.py` in the prose now
#: means a file that does not exist.
MOVED = {
    "ns": "oxml/ns",
    "revisions": "oxml/revisions",
    "textmap": "oxml/textmap",
    "edits": "oxml/edits",
    "diffing": "oxml/diffing",
    "clauses": "structure/clauses",
    "segments": "structure/segments",
    "redline": "editing/redline",
    "review": "editing/review",
    "compare": "editing/compare",
    "paragraphs": "editing/paragraphs",
    "actions": "planning/actions",
    "merge": "planning/merge",
    "agent": "planning/agent",
    "chunked": "planning/chunked",
    "pipeline": "planning/pipeline",
}
STALE_MODULE = re.compile(r"`(" + "|".join(sorted(MOVED, key=len, reverse=True)) + r")\.py`")

#: `id['...']` or `id('...')` -- mermaid only accepts double quotes here.
SINGLE_QUOTED_LABEL = re.compile(r"""[\w\]\)]\s*[\[\(\{]+\s*'""")

MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)


def blocks(text: str):
    """(1-based start line, source) for every mermaid block."""
    for m in MERMAID.finditer(text):
        yield text[: m.start()].count("\n") + 1, m.group(1)


def check(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(ROOT)
    problems = []

    if text.count("\n```") % 2:
        problems.append(f"{rel}: unbalanced code fence")

    for start, src in blocks(text):
        for offset, line in enumerate(src.splitlines()):
            if SINGLE_QUOTED_LABEL.search(line):
                problems.append(
                    f"{rel}:{start + offset + 1}: mermaid label uses single quotes; "
                    f'use ["..."] and &quot; for a literal quote'
                )

    for m in STALE_MODULE.finditer(text):
        line = text[: m.start()].count("\n") + 1
        problems.append(f"{rel}:{line}: `{m.group(1)}.py` moved -- write `{MOVED[m.group(1)]}.py`")

    for link in sorted(set(re.findall(r"\]\(([^)]+)\)", text))):
        if link.startswith(("http", "#", "mailto:")):
            continue
        if not (path.parent / link.split("#")[0]).resolve().exists():
            problems.append(f"{rel}: broken link -> {link}")

    return problems


def parse_diagrams() -> list[str]:
    """Hand every block to the real mermaid parser. Needs npx."""
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        for path in DOCS:
            for n, (start, src) in enumerate(blocks(path.read_text(encoding="utf-8")), 1):
                mmd = Path(tmp) / f"{path.stem}_{n}.mmd"
                mmd.write_text(src, encoding="utf-8")
                out = mmd.with_suffix(".svg")
                run = subprocess.run(
                    [
                        "npx",
                        "--yes",
                        "@mermaid-js/mermaid-cli@11",
                        "-i",
                        str(mmd),
                        "-o",
                        str(out),
                        "-q",
                    ],
                    capture_output=True,
                    text=True,
                )
                if run.returncode or not out.exists():
                    detail = (run.stderr or run.stdout).strip().splitlines()
                    why = next(
                        (line for line in detail if "rror" in line or "Expecting" in line),
                        detail[-1] if detail else "?",
                    )
                    problems.append(
                        f"{path.relative_to(ROOT)}:{start}: mermaid block {n} -- {why[:140]}"
                    )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--mermaid",
        action="store_true",
        help="also parse every diagram with mermaid-cli (slow, needs npx)",
    )
    args = ap.parse_args(argv)

    problems: list[str] = []
    for path in DOCS:
        problems += check(path)
    total = sum(len(list(blocks(p.read_text(encoding="utf-8")))) for p in DOCS)
    print(f"checked {len(DOCS)} files, {total} mermaid blocks")

    if args.mermaid:
        print("parsing every diagram with mermaid-cli ...")
        problems += parse_diagrams()

    if problems:
        print()
        for p in problems:
            print(f"  {p}")
        print(f"\n{len(problems)} problem(s)")
        return 1
    print("all good")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
