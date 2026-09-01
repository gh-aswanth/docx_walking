# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Word-Compare style redline: diff two ``.docx`` files into one marked-up file.

The output is built *on top of the original* so styles, numbering, headers and
section setup are preserved; only content that actually differs is touched.
New paragraphs are grafted in from the revised file so their own formatting
survives.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import docx
from docx.text.paragraph import Paragraph
from lxml import etree

from ..oxml import edits
from ..oxml.ns import qn
from ..oxml.textmap import paragraph_text
from .redline import Redliner

_P = qn("w:p")
_TBL = qn("w:tbl")
_TR = qn("w:tr")
_TC = qn("w:tc")

#: Below this token-similarity we treat a paragraph pair as unrelated and emit
#: a delete + insert instead of an in-place word diff.
SIMILARITY_FLOOR = 0.45


@dataclass
class CompareStats:
    paragraphs_changed: int = 0
    paragraphs_inserted: int = 0
    paragraphs_deleted: int = 0
    rows_inserted: int = 0
    rows_deleted: int = 0
    cells_changed: int = 0

    def format(self) -> str:
        return (
            f"paragraphs: {self.paragraphs_changed} changed, "
            f"{self.paragraphs_inserted} inserted, {self.paragraphs_deleted} deleted; "
            f"rows: {self.rows_inserted} inserted, {self.rows_deleted} deleted; "
            f"cells: {self.cells_changed} changed"
        )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _block_key(el: etree._Element) -> str:
    """Comparison key for a body-level block (paragraph or table)."""
    if el.tag == _P:
        return "P:" + _normalize(paragraph_text(el))
    if el.tag == _TBL:
        return "T:" + str(len(el.findall(_TR)))
    return "X:" + el.tag


def _blocks(root: etree._Element) -> list[etree._Element]:
    return [el for el in root if el.tag in (_P, _TBL)]


def compare_into(
    rl: Redliner,
    revised: str | Path,
    similarity_floor: float = SIMILARITY_FLOOR,
) -> CompareStats:
    """Mark up an *already open* :class:`Redliner` against ``revised``.

    Split out from :func:`compare_documents` so a compare can be one stage of a
    longer run -- see :func:`docx_redline.planning.pipeline.full_redline`, which layers
    scripted action items on top of a compare in the same document.
    """
    revised_doc = docx.Document(str(revised))
    stats = CompareStats()
    _compare_container(
        rl, rl.document.element.body, revised_doc.element.body, stats, similarity_floor
    )
    return stats


def compare_documents(
    original: str | Path,
    revised: str | Path,
    author: str = "Compare",
    date=None,
    track_changes: bool = True,
    similarity_floor: float = SIMILARITY_FLOOR,
) -> tuple[Redliner, CompareStats]:
    """Return a :class:`Redliner` over ``original`` marked up against ``revised``."""
    rl = Redliner(original, author=author, date=date, track_changes=track_changes)
    return rl, compare_into(rl, revised, similarity_floor)


def redline_files(
    original: str | Path,
    revised: str | Path,
    output: str | Path,
    **kwargs,
) -> CompareStats:
    """Convenience wrapper: compare and save in one call."""
    rl, stats = compare_documents(original, revised, **kwargs)
    rl.save(output)
    return stats


# ---------------------------------------------------------------------------


def _compare_container(
    rl: Redliner,
    old_root: etree._Element,
    new_root: etree._Element,
    stats: CompareStats,
    floor: float,
) -> None:
    old_blocks = _blocks(old_root)
    new_blocks = _blocks(new_root)
    matcher = SequenceMatcher(
        None,
        [_block_key(b) for b in old_blocks],
        [_block_key(b) for b in new_blocks],
        autojunk=False,
    )
    # Track where to graft insertions when the old side has nothing to anchor to.
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for old, new in zip(old_blocks[i1:i2], new_blocks[j1:j2], strict=False):
                if old.tag == _TBL and new.tag == _TBL:
                    _compare_table(rl, old, new, stats, floor)
            continue
        if tag == "delete":
            _delete_blocks(rl, old_blocks[i1:i2], stats)
        elif tag == "insert":
            anchor = _anchor_for(old_blocks, i1)
            _insert_blocks(rl, anchor, new_blocks[j1:j2], stats, old_root)
        else:
            _replace_blocks(rl, old_blocks[i1:i2], new_blocks[j1:j2], stats, floor, old_root, i1)


def _anchor_for(old_blocks: list[etree._Element], index: int) -> etree._Element | None:
    if index == 0:
        return None
    return old_blocks[index - 1]


def _delete_blocks(rl: Redliner, blocks, stats: CompareStats) -> None:
    for block in blocks:
        if block.tag == _P:
            rl.delete_paragraph(Paragraph(block, rl.document))
            stats.paragraphs_deleted += 1
        elif block.tag == _TBL:
            for tr in block.findall(_TR):
                edits.mark_row_deleted(tr, rl.ctx)
                stats.rows_deleted += 1


def _insert_blocks(rl: Redliner, anchor, blocks, stats: CompareStats, old_root) -> None:
    for block in blocks:
        clone = copy.deepcopy(block)
        if anchor is not None:
            anchor.addnext(clone)
        else:
            first = _blocks(old_root)
            if first:
                first[0].addprevious(clone)
            else:
                old_root.append(clone)
        if clone.tag == _P:
            edits.mark_paragraph_inserted(clone, rl.ctx)
            stats.paragraphs_inserted += 1
        elif clone.tag == _TBL:
            for tr in clone.findall(_TR):
                edits.mark_row_inserted(tr, rl.ctx)
                stats.rows_inserted += 1
        anchor = clone


def _replace_blocks(rl, old_blocks, new_blocks, stats, floor, old_root, old_index) -> None:
    """Pair up changed blocks; leftovers become pure inserts/deletes."""
    pairs = min(len(old_blocks), len(new_blocks))
    for old, new in zip(old_blocks[:pairs], new_blocks[:pairs], strict=False):
        if old.tag == _P and new.tag == _P:
            old_text = paragraph_text(old)
            new_text = paragraph_text(new)
            if _similarity(old_text, new_text) < floor:
                rl.delete_paragraph(Paragraph(old, rl.document))
                stats.paragraphs_deleted += 1
                clone = copy.deepcopy(new)
                old.addnext(clone)
                edits.mark_paragraph_inserted(clone, rl.ctx)
                stats.paragraphs_inserted += 1
            else:
                changed = rl.set_paragraph_text(Paragraph(old, rl.document), new_text)
                if changed:
                    stats.paragraphs_changed += 1
        elif old.tag == _TBL and new.tag == _TBL:
            _compare_table(rl, old, new, stats, floor)
        else:
            _delete_blocks(rl, [old], stats)
            _insert_blocks(rl, old, [new], stats, old_root)
    if len(old_blocks) > pairs:
        _delete_blocks(rl, old_blocks[pairs:], stats)
    if len(new_blocks) > pairs:
        anchor = old_blocks[-1] if old_blocks else _anchor_for(_blocks(old_root), old_index)
        _insert_blocks(rl, anchor, new_blocks[pairs:], stats, old_root)


def _similarity(a: str, b: str) -> float:
    a, b = _normalize(a), _normalize(b)
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------


def _row_key(tr: etree._Element) -> str:
    return " | ".join(_normalize(_cell_text(tc)) for tc in tr.findall(_TC))


def _cell_text(tc: etree._Element) -> str:
    return "\n".join(paragraph_text(p) for p in tc.findall(_P))


def _compare_table(rl: Redliner, old_tbl, new_tbl, stats: CompareStats, floor: float) -> None:
    old_rows = old_tbl.findall(_TR)
    new_rows = new_tbl.findall(_TR)
    matcher = SequenceMatcher(
        None, [_row_key(r) for r in old_rows], [_row_key(r) for r in new_rows], autojunk=False
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("delete", "replace"):
            pairs = min(i2 - i1, j2 - j1) if tag == "replace" else 0
            for offset in range(pairs):
                _compare_row(rl, old_rows[i1 + offset], new_rows[j1 + offset], stats)
            for tr in old_rows[i1 + pairs : i2]:
                edits.mark_row_deleted(tr, rl.ctx)
                stats.rows_deleted += 1
            if tag == "replace" and j1 + pairs < j2:
                anchor = old_rows[i2 - 1]
                for new_tr in new_rows[j1 + pairs : j2]:
                    anchor = _graft_row(rl, anchor, new_tr, stats)
        elif tag == "insert":
            anchor = old_rows[i1 - 1] if i1 > 0 else None
            for new_tr in new_rows[j1:j2]:
                if anchor is None:
                    clone = copy.deepcopy(new_tr)
                    _first_row_position(old_tbl).addprevious(clone)
                    edits.mark_row_inserted(clone, rl.ctx)
                    stats.rows_inserted += 1
                    anchor = clone
                else:
                    anchor = _graft_row(rl, anchor, new_tr, stats)


def _first_row_position(tbl: etree._Element) -> etree._Element:
    rows = tbl.findall(_TR)
    return rows[0] if rows else tbl


def _graft_row(rl: Redliner, anchor: etree._Element, new_tr, stats: CompareStats):
    clone = copy.deepcopy(new_tr)
    anchor.addnext(clone)
    edits.mark_row_inserted(clone, rl.ctx)
    stats.rows_inserted += 1
    return clone


def _compare_row(rl: Redliner, old_tr, new_tr, stats: CompareStats) -> None:
    old_cells = old_tr.findall(_TC)
    new_cells = new_tr.findall(_TC)
    for old_tc, new_tc in zip(old_cells, new_cells, strict=False):
        old_paras = old_tc.findall(_P)
        new_text = _cell_text(new_tc)
        if _cell_text(old_tc) == new_text:
            continue
        if old_paras:
            changed = rl.set_paragraph_text(Paragraph(old_paras[0], rl.document), new_text)
            if changed:
                stats.cells_changed += 1
        for extra in old_paras[1:]:
            edits.mark_paragraph_deleted(extra, rl.ctx)
