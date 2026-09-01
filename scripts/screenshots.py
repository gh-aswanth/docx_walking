"""Render the examples' output documents to PNGs for the README.

    uv run python scripts/screenshots.py            # regenerate docs/images/
    uv run python scripts/screenshots.py --check    # fail if any is stale

A redline is a visual artefact. Describing one in prose asks the reader to take
it on faith; a picture of the actual output does not. These are generated from
the real files `examples/run_all.py` writes, so a screenshot cannot drift away
from what the library currently produces.

Pipeline: .docx -> PDF (LibreOffice) -> PNG (pdftoppm), then cropped to the band
that carries the change. The crop is located by searching the PDF's own text
layer for a marker phrase, so it follows the content instead of being a
hard-coded rectangle that silently slides off.

Requires `soffice` and `pdftoppm`/`pdftotext` (poppler):

    brew install --cask libreoffice && brew install poppler
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "examples" / "output"
IMAGES = ROOT / "docs" / "images"

DPI = 110
#: Vertical padding around a located marker, in PDF points (72 = one inch).
PAD_ABOVE, PAD_BELOW = 46, 46


@dataclass(frozen=True)
class Shot:
    name: str  # output file stem, and the anchor used in the README
    source: str  # a .docx under examples/output/
    page: int
    marker: str | None = None  # crop to the band containing this phrase
    notes: bool = False  # export comments as margin balloons
    caption: str = ""
    pad: tuple[int, int] = (PAD_ABOVE, PAD_BELOW)  # points above/below the marker
    dpi: int = DPI  # a whole page needs less than a cropped detail


SHOTS = [
    Shot(
        "quickstart",
        "01_quickstart.docx",
        2,
        "forty-five (45) days",
        caption="`replace_text` and `insert_text_after`: the old span struck, "
        "the new text underlined, a change bar in the margin.",
    ),
    Shot(
        "comments",
        "12_edits_and_notes.docx",
        2,
        "forty-five (45) days",
        notes=True,
        caption="A `ReviewNote` anchored to its span, signed by the agent that raised it.",
    ),
    Shot(
        "paragraph-delete",
        "01_quickstart.docx",
        1,
        "Reservation of Rights",
        caption="`delete_paragraph`: the whole clause struck, paragraph mark included.",
    ),
    # "Countersigned by" is in an inserted row that pdftotext does not surface,
    # so anchor on the cell edit instead and open the band out to hold the table.
    Shot(
        "tables",
        "07_tables.docx",
        5,
        "please print",
        pad=(150, 110),
        caption="`insert_table_row` and `set_cell_text`: a tracked row, and a "
        "word-level diff inside a cell.",
    ),
    Shot(
        "formatting",
        "08_formatting.docx",
        4,
        "Delaware",
        caption="`format_matching`: a `w:rPrChange`, so rejecting restores the old formatting.",
    ),
    Shot(
        "renumbering",
        "19_renumbering.docx",
        4,
        "Governing Law",
        caption="The cascade: one `move_clause`, and every sibling and cross-reference follows.",
    ),
    Shot(
        "compare",
        "23_compare.docx",
        2,
        "sixty (60) days",
        caption="`redline_files`: two documents diffed into one reviewable redline.",
    ),
    Shot(
        "action-items",
        "17_action_items.docx",
        1,
        "Affiliate",
        caption="29 action items applied at once, with 39 clauses renumbered.",
    ),
    Shot(
        "full-page",
        "17_action_items.docx",
        2,
        None,
        dpi=78,
        caption="A whole page of the result, as a reviewer sees it.",
    ),
]


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        sys.exit(
            f"error: {tool!r} not found.\n"
            "  brew install --cask libreoffice   # soffice\n"
            "  brew install poppler              # pdftoppm, pdftotext, pdfinfo"
        )
    return path


def to_pdf(docx: Path, out_dir: Path, *, notes: bool) -> Path:
    """LibreOffice headless. `notes` puts comments in the margin, as Word does."""
    fmt = "pdf"
    if notes:
        fmt = 'pdf:writer_pdf_Export:{"ExportNotesInMargin":{"type":"boolean","value":"true"}}'
    subprocess.run(
        [need("soffice"), "--headless", "--convert-to", fmt, "--outdir", str(out_dir), str(docx)],
        check=True,
        capture_output=True,
        text=True,
    )
    return out_dir / f"{docx.stem}.pdf"


def marker_band(pdf: Path, page: int, marker: str) -> tuple[float, float] | None:
    """(top, bottom) of the marker phrase on `page`, in PDF points from the top."""
    xml = subprocess.run(
        [need("pdftotext"), "-bbox", "-f", str(page), "-l", str(page), str(pdf), "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    ns = {"x": "http://www.w3.org/1999/xhtml"}
    words = ET.fromstring(xml).iter(f"{{{ns['x']}}}word")
    wanted = marker.split()[0].strip("(),.")
    for word in words:
        if wanted in (word.text or ""):
            return float(word.get("yMin")), float(word.get("yMax"))
    return None


def render(
    pdf: Path,
    page: int,
    dest: Path,
    band: tuple[float, float] | None,
    pad: tuple[int, int] = (PAD_ABOVE, PAD_BELOW),
    dpi: int = DPI,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        stem = Path(tmp) / "page"
        args = [need("pdftoppm"), "-png", "-r", str(dpi), "-f", str(page), "-l", str(page)]
        if band is not None:
            above, below = pad
            top = max(0, band[0] - above)
            height = (band[1] - band[0]) + above + below
            scale = dpi / 72
            args += ["-y", str(int(top * scale)), "-H", str(int(height * scale))]
        subprocess.run([*args, str(pdf), str(stem)], check=True, capture_output=True)
        produced = sorted(Path(tmp).glob("page*.png"))
        if not produced:
            raise RuntimeError(f"pdftoppm produced nothing for {pdf.name} page {page}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(produced[0], dest)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--check",
        action="store_true",
        help="regenerate into a temp dir and fail if anything differs",
    )
    ap.add_argument("--only", nargs="*", help="only these shot names")
    args = ap.parse_args(argv)

    missing = sorted({s.source for s in SHOTS if not (OUTPUT / s.source).exists()})
    if missing:
        sys.exit(f"error: run `python examples/run_all.py` first; missing: {', '.join(missing)}")

    shots = [s for s in SHOTS if not args.only or s.name in args.only]
    target = Path(tempfile.mkdtemp()) if args.check else IMAGES
    stale: list[str] = []

    with tempfile.TemporaryDirectory() as work:
        pdfs: dict[tuple[str, bool], Path] = {}
        for shot in shots:
            key = (shot.source, shot.notes)
            if key not in pdfs:
                sub = Path(work) / ("notes" if shot.notes else "plain")
                sub.mkdir(exist_ok=True)
                pdfs[key] = to_pdf(OUTPUT / shot.source, sub, notes=shot.notes)
            pdf = pdfs[key]

            band = marker_band(pdf, shot.page, shot.marker) if shot.marker else None
            if shot.marker and band is None:
                print(
                    f"  !! {shot.name}: marker {shot.marker!r} not on page {shot.page}"
                    f" -- rendering the whole page"
                )

            dest = target / f"{shot.name}.png"
            before = digest(IMAGES / f"{shot.name}.png")
            render(pdf, shot.page, dest, band, shot.pad, shot.dpi)
            size = dest.stat().st_size // 1024
            if args.check and digest(dest) != before:
                stale.append(shot.name)
            print(
                f"  {shot.name:<18} {shot.source:<24} p{shot.page}  {size:>4} KB"
                f"  {'cropped' if band else 'full page'}"
            )

    if args.check:
        shutil.rmtree(target, ignore_errors=True)
        if stale:
            print(f"\n{len(stale)} screenshot(s) out of date: {', '.join(stale)}")
            print("regenerate with: uv run python scripts/screenshots.py")
            return 1
        print("\nall screenshots current")
    else:
        print(f"\nwrote {len(shots)} image(s) to {IMAGES.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
