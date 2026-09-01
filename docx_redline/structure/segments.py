# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Seeing the whole document, and cutting it into reviewable pieces.

``ClauseTree`` answers "what is numbered here", which is the right model for
renumbering but the wrong one for review: it drops recitals, signature blocks,
tables and every exhibit, and it caps each clause at the outline's ``body_chars``.
On the sample contract that hides 39% of the paragraphs -- including the fee
schedule and the SLA.

This module answers the other question: *what does the document actually say*.
It walks every block in body order, works out the document's structure by
whichever signal the file happens to carry, and renders the lot for a model to
read. The same block walk then packs into :class:`DocSegment` pieces sized for
one request.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from lxml import etree

from ..oxml.ns import qn
from .clauses import Clause, ClauseTree

__all__ = [
    "Block",
    "DocSegment",
    "count_headings",
    "detect_strategy",
    "iter_blocks",
    "level_resolver",
    "render_document",
    "render_segment",
    "segment_document",
]

#: Rough characters per token. Provider-agnostic and free; good enough for
#: packing, which only needs to avoid overshooting a budget.
CHARS_PER_TOKEN = 4

#: How many top-level headings before the heading strategy is trusted.
MIN_HEADINGS = 8
#: Share of non-empty paragraphs that must be numbered to trust clause numbers.
MIN_NUMBERED_SHARE = 0.25

_HEADING_STYLE = re.compile(r"^heading([1-9])$")


# ---------------------------------------------------------------------------
# blocks
# ---------------------------------------------------------------------------
@dataclass
class Block:
    """One thing in the body: a paragraph, or a whole table."""

    kind: str  # "para" | "table"
    ordinal: int  # position in the body-level block sequence
    p: etree._Element | None = None
    tbl: etree._Element | None = None
    table_index: int | None = None  # document-global index, as `rl.tables()` sees it
    clause: Clause | None = None  # set when the paragraph carries a clause number
    level: int = 0  # 1-based outline depth; 0 = body text
    text: str = ""

    @property
    def is_heading(self) -> bool:
        return self.level > 0

    @property
    def chars(self) -> int:
        return len(self.text)


def iter_blocks(body: etree._Element, tree: ClauseTree | None = None) -> list[Block]:
    """Every paragraph and table in the body, in reading order.

    Table *cells* are not separate blocks: a table is reviewed and rendered as a
    unit, and `update_cell` addresses it by (table, row, col) anyway.
    """
    from ..oxml.textmap import paragraph_text

    level_of = level_resolver(body)
    # Hold the clause objects (and so their paragraph proxies) alive for the
    # whole walk, for the same reason `level_resolver` is not a dict.
    numbered = {id(c.p): c for c in (tree.all() if tree is not None else [])}

    blocks: list[Block] = []
    table_index = 0
    for child in body:
        if child.tag == qn("w:p"):
            text = paragraph_text(child)
            clause = numbered.get(id(child))
            blocks.append(
                Block(
                    kind="para",
                    ordinal=len(blocks),
                    p=child,
                    clause=clause,
                    level=clause.level if clause else level_of(child),
                    text=text,
                )
            )
        elif child.tag == qn("w:tbl"):
            blocks.append(
                Block(
                    kind="table",
                    ordinal=len(blocks),
                    tbl=child,
                    table_index=table_index,
                    text=_table_text(child),
                )
            )
            table_index += 1
    return blocks


def _table_text(tbl: etree._Element) -> str:
    from ..oxml.textmap import paragraph_text

    rows = []
    for tr in tbl.findall(qn("w:tr")):
        cells = [
            " ".join(paragraph_text(p) for p in tc.findall(qn("w:p"))).strip()
            for tc in tr.findall(qn("w:tc"))
        ]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# structure detection
# ---------------------------------------------------------------------------
def level_resolver(body: etree._Element):
    """Return ``p -> heading level`` (0 = body text) for this document.

    Four signals in descending reliability: the first three are properties Word
    actually wrote, the fourth is a guess. Whether to fall back to the guess is a
    whole-document decision, so it is made once here rather than per paragraph.

    Deliberately a function, not a ``dict`` keyed by ``id(p)``: lxml hands out
    proxy objects on demand and frees them when the last reference goes, so such
    a map silently loses entries -- and starts matching unrelated paragraphs once
    CPython recycles an address.
    """
    if any(_explicit_level(p) is not None for p in body.iter(qn("w:p"))):
        return lambda p: _explicit_level(p) or 0
    return lambda p: 1 if _looks_like_a_heading(p) else 0


def count_headings(body: etree._Element) -> int:
    level_of = level_resolver(body)
    return sum(1 for p in body.iter(qn("w:p")) if level_of(p))


def _explicit_level(p: etree._Element) -> int | None:
    ppr = p.find(qn("w:pPr"))
    if ppr is None:
        return None

    outline = ppr.find(qn("w:outlineLvl"))
    if outline is not None:
        raw = outline.get(qn("w:val"))
        if raw and raw.isdigit():
            return int(raw) + 1

    style = ppr.find(qn("w:pStyle"))
    if style is not None:
        match = _HEADING_STYLE.match((style.get(qn("w:val")) or "").replace(" ", "").lower())
        if match:
            return int(match.group(1))

    numpr = ppr.find(qn("w:numPr"))
    if numpr is not None:
        ilvl = numpr.find(qn("w:ilvl"))
        raw = ilvl.get(qn("w:val")) if ilvl is not None else "0"
        if raw and raw.isdigit():
            return int(raw) + 1
    return None


def _looks_like_a_heading(p: etree._Element) -> bool:
    """Typographic guess: short, unpunctuated, and set apart by bold or caps."""
    from ..oxml.textmap import iter_visible_runs, paragraph_text

    text = paragraph_text(p).strip()
    if not text or len(text) > 80 or text.endswith((".", ";", ":", ",")):
        return False
    runs = list(iter_visible_runs(p))
    if not runs:
        return False
    bold = all(
        r.find(qn("w:rPr")) is not None and r.find(qn("w:rPr")).find(qn("w:b")) is not None
        for r in runs
    )
    return bold or (text.upper() == text and any(c.isalpha() for c in text))


def detect_strategy(body: etree._Element, tree: ClauseTree | None = None) -> str:
    """``"clauses"``, ``"headings"`` or ``"windows"``, whichever the file supports."""
    tree = tree if tree is not None else ClauseTree(body)
    from ..oxml.textmap import paragraph_text

    paragraphs = [p for p in body.iter(qn("w:p")) if paragraph_text(p).strip()]
    numbered = len(tree.all())
    if len(tree.sections) >= 3 and paragraphs and numbered / len(paragraphs) >= MIN_NUMBERED_SHARE:
        return "clauses"
    if count_headings(body) >= MIN_HEADINGS:
        return "headings"
    return "windows"


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def render_blocks(blocks: Sequence[Block]) -> str:
    """The document as a reviewer would read it -- complete and untruncated.

    Numbered clauses already carry their number in the text, so they are not
    re-labelled; they are only indented to show depth. Tables get explicit
    ``table``/``row`` markers because that is how `update_cell` addresses them
    and there is no other way to point at a cell.
    """
    lines: list[str] = []
    for block in blocks:
        if block.kind == "table":
            lines.append(f"[table {block.table_index}]")
            for index, row in enumerate(block.text.split("\n")):
                lines.append(f"  row {index}: {row}")
            continue
        text = block.text.strip()
        if not text:
            continue
        indent = "  " * max(0, block.level - 1) if block.level else ""
        lines.append(f"{indent}{text}")
    return "\n".join(lines)


def render_document(body: etree._Element, tree: ClauseTree | None = None) -> str:
    """Render the entire body: clauses, recitals, tables, exhibits, signatures."""
    tree = tree if tree is not None else ClauseTree(body)
    return render_blocks(iter_blocks(body, tree))


def render_segment(seg: DocSegment) -> str:
    return render_blocks(seg.blocks)


# ---------------------------------------------------------------------------
# segmentation
# ---------------------------------------------------------------------------
@dataclass
class DocSegment:
    """A contiguous run of blocks small enough to review in one request."""

    id: str
    index: int
    strategy: str
    blocks: list[Block] = field(default_factory=list)
    title: str = ""

    @property
    def labels(self) -> frozenset[str]:
        """Clause numbers this segment owns -- the reduce step's scope filter."""
        return frozenset(
            child.label for b in self.blocks if b.clause is not None for child in b.clause.walk()
        )

    @property
    def tables(self) -> list[int]:
        return [b.table_index for b in self.blocks if b.kind == "table"]

    @property
    def chars(self) -> int:
        return sum(b.chars for b in self.blocks)

    @property
    def approx_tokens(self) -> int:
        return max(1, self.chars // CHARS_PER_TOKEN)

    def render(self) -> str:
        return render_blocks(self.blocks)

    def split(self) -> tuple[DocSegment, DocSegment] | None:
        """Halve the segment at a structural boundary, or ``None`` if indivisible.

        Used when a model truncates on a span: the fix is a smaller span, but
        only if there is somewhere safe to cut. Prefer a heading boundary near
        the middle so a clause is still never split.
        """
        if len(self.blocks) < 2:
            return None
        middle = len(self.blocks) // 2
        headings = [
            index
            for index, block in enumerate(self.blocks)
            if 0 < index < len(self.blocks) and block.kind == "para" and block.is_heading
        ]
        cut = min(headings, key=lambda i: abs(i - middle)) if headings else middle
        left, right = self.blocks[:cut], self.blocks[cut:]
        if not left or not right:
            return None
        return (
            DocSegment(f"{self.id}a", self.index, self.strategy, left, _title_for(left)),
            DocSegment(f"{self.id}b", self.index, self.strategy, right, _title_for(right)),
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<DocSegment {self.id} {self.title[:32]!r} "
            f"blocks={len(self.blocks)} ~{self.approx_tokens}tok>"
        )


def segment_document(
    body: etree._Element,
    *,
    budget_tokens: int = 25_000,
    strategy: str = "auto",
    tree: ClauseTree | None = None,
) -> list[DocSegment]:
    """Pack the document into request-sized pieces on structural boundaries.

    A *unit* is a heading and everything under it until the next heading of the
    same or shallower depth, so a clause is never cut in half. Units are packed
    greedily; a unit bigger than the budget becomes its own segment rather than
    being split mid-clause (the map pass splits it again only if the model
    truncates).
    """
    tree = tree if tree is not None else ClauseTree(body)
    if strategy == "auto":
        strategy = detect_strategy(body, tree)
    blocks = iter_blocks(body, tree)
    if not blocks:
        return []

    budget_chars = max(1, budget_tokens) * CHARS_PER_TOKEN
    segments: list[DocSegment] = []
    current: list[Block] = []

    def flush() -> None:
        if not current:
            return
        seg = DocSegment(
            id=f"S{len(segments):02d}",
            index=len(segments),
            strategy=strategy,
            blocks=list(current),
            title=_title_for(current),
        )
        segments.append(seg)
        current.clear()

    for unit in _units(blocks, strategy):
        unit_chars = sum(b.chars for b in unit)
        used = sum(b.chars for b in current)
        if current and used + unit_chars > budget_chars:
            flush()
        current.extend(unit)
    flush()
    return segments


def _units(blocks: list[Block], strategy: str) -> Iterator[list[Block]]:
    """Group blocks into indivisible units, so packing never splits a clause."""
    if strategy == "windows":
        for block in blocks:
            yield [block]
        return

    top = _top_level(blocks, strategy)
    unit: list[Block] = []
    for block in blocks:
        starts_unit = block.kind == "para" and block.level == top and block.level > 0
        if starts_unit and unit:
            yield unit
            unit = []
        unit.append(block)
    if unit:
        yield unit


def _top_level(blocks: list[Block], strategy: str) -> int:
    """The shallowest heading depth present -- what a unit starts at."""
    levels = [b.level for b in blocks if b.kind == "para" and b.level > 0]
    return min(levels) if levels else 0


def _title_for(blocks: Sequence[Block]) -> str:
    for block in blocks:
        if block.kind == "para" and block.is_heading and block.text.strip():
            return block.text.strip()[:80]
    for block in blocks:
        if block.text.strip():
            return block.text.strip()[:80]
    return ""
