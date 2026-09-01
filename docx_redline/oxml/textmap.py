# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Character-offset map over a paragraph, plus run splitting.

Word stores paragraph text as an arbitrary sequence of runs, and a run may
itself hold several text nodes interleaved with tabs, breaks, drawings and
field characters.  To redline a *substring* we must be able to (a) address the
paragraph by flat character offset and (b) force a run boundary at any offset
so that a range can be wrapped in ``w:ins`` / ``w:del`` wholesale.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from lxml import etree

from .elements import clone_shell
from .ns import qn

#: Containers that hold runs and whose content is *visible* in the current
#: (i.e. "all markup accepted") text of the paragraph.
VISIBLE_WRAPPERS = (
    "ins",
    "moveTo",
    "hyperlink",
    "smartTag",
    "sdt",
    "sdtContent",
    "customXml",
    "bdo",
    "dir",
)
#: Containers whose content has already been struck out -- not part of current text.
HIDDEN_WRAPPERS = ("w:del", "w:moveFrom")

_RUN = qn("w:r")
_T = qn("w:t")
_DELTEXT = qn("w:delText")
_INSTRTEXT = qn("w:instrText")
_TAB = qn("w:tab")
_BR = qn("w:br")
_CR = qn("w:cr")
_NOBREAKHYPHEN = qn("w:noBreakHyphen")

#: Run children that occupy exactly one character in our flat coordinate space.
ATOMIC_CHARS = {_TAB: "\t", _BR: "\n", _CR: "\n", _NOBREAKHYPHEN: "-"}


@dataclass
class Segment:
    """One contiguous stretch of characters coming from a single XML node."""

    run: etree._Element
    node: etree._Element  # the w:t / w:tab / ... that produced the text
    start: int
    end: int
    text: str


class ParagraphText:
    """Flat text view of a ``w:p``, ignoring already-deleted content."""

    def __init__(self, p: etree._Element) -> None:
        self.p = p
        self.segments: list[Segment] = []
        self._build()

    # -- construction ----------------------------------------------------
    def _build(self) -> None:
        self.segments = []
        pos = 0
        for run in iter_visible_runs(self.p):
            for child in run:
                if child.tag in (_T, _INSTRTEXT):
                    text = child.text or ""
                    if not text:
                        continue
                    self.segments.append(Segment(run, child, pos, pos + len(text), text))
                    pos += len(text)
                elif child.tag in ATOMIC_CHARS:
                    text = ATOMIC_CHARS[child.tag]
                    self.segments.append(Segment(run, child, pos, pos + 1, text))
                    pos += 1
        self.text = "".join(s.text for s in self.segments)

    def refresh(self) -> ParagraphText:
        self._build()
        return self

    def __len__(self) -> int:
        return len(self.text)

    # -- queries ---------------------------------------------------------
    def run_span(self, run: etree._Element) -> tuple[int, int] | None:
        """(start, end) character span of ``run``, or None if it has no text."""
        spans = [s for s in self.segments if s.run is run]
        if not spans:
            return None
        return spans[0].start, spans[-1].end

    def runs_in(self, start: int, end: int) -> list[etree._Element]:
        """Runs fully contained in ``[start, end)`` (call after ``split_at``)."""
        out: list[etree._Element] = []
        for seg in self.segments:
            if (
                seg.start >= start
                and seg.end <= end
                and (not out or out[-1] is not seg.run)
                and seg.run not in out
            ):
                out.append(seg.run)
        return out

    def find(self, needle: str, start: int = 0) -> int:
        return self.text.find(needle, start)


def iter_visible_runs(container: etree._Element):
    """Yield ``w:r`` elements that contribute to the paragraph's current text.

    Recurses through hyperlinks/ins/smartTag wrappers and skips anything already
    marked deleted or moved-away.
    """
    hidden = {qn(t) for t in HIDDEN_WRAPPERS}
    for child in container:
        if child.tag == _RUN:
            yield child
        elif child.tag in hidden:
            continue
        elif isinstance(child.tag, str) and child.tag.startswith("{") and len(child):
            local = child.tag.split("}", 1)[1]
            if local in VISIBLE_WRAPPERS:
                yield from iter_visible_runs(child)


def paragraph_text(p: etree._Element) -> str:
    return ParagraphText(p).text


# ---------------------------------------------------------------------------
# splitting
# ---------------------------------------------------------------------------


def split_run(run: etree._Element, local_offset: int) -> etree._Element | None:
    """Split ``run`` at ``local_offset`` characters in; return the new trailing run.

    Returns ``None`` when the offset already lies on a run boundary.
    """
    if local_offset <= 0:
        return None
    pos = 0
    split_index: int | None = None
    for index, child in enumerate(run):
        if child.tag in (_T, _INSTRTEXT):
            text = child.text or ""
            if pos + len(text) > local_offset:
                cut = local_offset - pos
                if cut == 0:
                    split_index = index
                else:
                    tail_text = text[cut:]
                    child.text = text[:cut]
                    _mark_preserve(child)
                    tail = copy.deepcopy(child)
                    tail.text = tail_text
                    _mark_preserve(tail)
                    child.addnext(tail)
                    split_index = index + 1
                break
            pos += len(text)
        elif child.tag in ATOMIC_CHARS:
            if pos + 1 > local_offset:
                split_index = index
                break
            pos += 1
        # Boundary lands between children -- but only split if what follows
        # still carries content.
        if pos == local_offset and index + 1 < len(run):
            split_index = index + 1
            break
    if split_index is None or split_index >= len(run):
        return None

    new_run = clone_shell(run)
    rpr = run.find(qn("w:rPr"))
    if rpr is not None:
        new_run.append(copy.deepcopy(rpr))
    children = list(run)[split_index:]
    if not children or all(c.tag == qn("w:rPr") for c in children):
        return None
    for child in children:
        run.remove(child)
        new_run.append(child)
    run.addnext(new_run)
    return new_run


def _mark_preserve(node: etree._Element) -> None:
    text = node.text or ""
    if text != text.strip() or text == "":
        node.set(qn("xml:space"), "preserve")


def split_at(p: etree._Element, offset: int) -> None:
    """Guarantee a run boundary at character ``offset`` of paragraph ``p``."""
    view = ParagraphText(p)
    if offset <= 0 or offset >= len(view):
        return
    for run in dict.fromkeys(seg.run for seg in view.segments):
        span = view.run_span(run)
        if span is None:
            continue
        start, end = span
        if start < offset < end:
            split_run(run, offset - start)
            return


def split_range(p: etree._Element, start: int, end: int) -> ParagraphText:
    """Force boundaries at both ends of ``[start, end)`` and return a fresh view."""
    split_at(p, end)
    split_at(p, start)
    return ParagraphText(p)
