# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Clause structure: parsing, structural moves, renumbering, cross-references.

Contracts number their clauses in the body text (``12.1  Governing Law. ...``)
rather than with Word's auto-numbering, so moving a clause is not one edit but
a cascade:

* the clause takes a new number at its destination,
* every sibling after it at the destination shifts down,
* every sibling after its old position at the source shifts up,
* and every cross-reference in the document ("as set out in Section 4.2")
  has to follow.

This module owns that cascade.  It reads the document into a clause tree,
lets callers move/insert/delete nodes, then diffs the old numbering against the
positionally-derived new numbering and reports exactly which labels and which
references have to change.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from lxml import etree

from ..errors import ClauseError
from ..oxml.ns import qn
from ..oxml.textmap import paragraph_text

#: ``12.1`` / ``12.1.3`` -- a sub-clause, at least two components.
CLAUSE_RE = re.compile(r"^[ \t]*(\d+(?:\.\d+)+)\.?(?=[ \t ])")
#: ``12.`` -- a top-level section heading.
SECTION_RE = re.compile(r"^[ \t]*(\d+)\.(?=[ \t ])")

#: Words that introduce a cross-reference.  Matched case-insensitively.
REFERENCE_WORDS = (
    "section",
    "sections",
    "article",
    "articles",
    "clause",
    "clauses",
    "paragraph",
    "paragraphs",
    "subsection",
    "subsections",
)
_REF_WORD_RE = re.compile(r"\b(" + "|".join(REFERENCE_WORDS) + r")\b", re.IGNORECASE)
_REF_NUMBER_RE = re.compile(r"[ \t ]*(\d+(?:\.\d+)*)")
_REF_JOINER_RE = re.compile(r"[ \t ]*(?:,|;|and|or|through|to|-|–|—|&)")


# ---------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------
@dataclass
class Clause:
    """One numbered paragraph, plus any numbered children beneath it."""

    p: etree._Element
    label: str  # "12.1" as written in the document
    number: tuple[int, ...]  # (12, 1)
    span: tuple[int, int]  # char offsets of the label in the paragraph
    title: str  # "Governing Law" when the clause has one
    children: list[Clause] = field(default_factory=list)
    parent: Clause | None = None
    inserted: bool = False  # whole paragraph is a tracked insertion
    moved: bool = False  # paragraph is a move destination

    @property
    def level(self) -> int:
        return len(self.number)

    @property
    def text(self) -> str:
        return paragraph_text(self.p)

    @property
    def body(self) -> str:
        """Clause text with its number stripped off the front."""
        return self.text[self.span[1] :].lstrip(" . \t")

    def walk(self) -> Iterator[Clause]:
        yield self
        for child in self.children:
            yield from child.walk()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Clause {self.label} {self.title[:32]!r} children={len(self.children)}>"


class LabelSnapshot:
    """Paragraph -> the label it had before any structural work started.

    Keyed by ``id()`` of the ``w:p``, which is only safe because the snapshot
    *also keeps a reference to the element*.  lxml hands out proxy objects on
    demand and frees them when the last reference goes; a bare ``id()`` key
    silently starts matching an unrelated paragraph once CPython recycles the
    address, which is exactly what happens when the clause tree is reloaded.
    """

    __slots__ = ("_items",)

    def __init__(self, clauses: Iterable[Clause]) -> None:
        self._items: dict[int, tuple[etree._Element, str]] = {
            id(clause.p): (clause.p, clause.label) for clause in clauses
        }

    def get(self, p: etree._Element, default: str | None = None) -> str | None:
        entry = self._items.get(id(p))
        return entry[1] if entry is not None else default

    def __contains__(self, p: etree._Element) -> bool:
        return id(p) in self._items

    def items(self):
        """``(paragraph, label)`` pairs, so callers can spot clauses that vanished."""
        return self._items.values()

    def __len__(self) -> int:
        return len(self._items)


@dataclass
class Renumbering:
    """The full consequence of a structural change."""

    #: clause -> (old label, new label) for clauses whose number moved
    relabelled: list[tuple[Clause, str, str]] = field(default_factory=list)
    #: old label -> new label, for rewriting cross-references
    mapping: dict[str, str] = field(default_factory=dict)
    #: references pointing at clauses that were deleted outright
    dangling: list[tuple[etree._Element, str]] = field(default_factory=list)
    #: every old label still carried by a surviving clause.  A move keeps its
    #: label alive on the destination copy; only a real deletion drops one.
    claimed: set[str] = field(default_factory=set)

    def __bool__(self) -> bool:
        return bool(self.relabelled)


@dataclass
class ReferenceEdit:
    """A cross-reference that has to be rewritten, located by char offsets."""

    p: etree._Element
    start: int
    end: int
    old: str
    new: str
    context: str


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def _is_removed_paragraph(p: etree._Element) -> bool:
    """True when the paragraph is on its way out -- struck, or moved away.

    Such paragraphs must not take part in numbering: the whole point of the
    renumbering pass is to number the document as it will read once the
    redline is accepted.
    """
    ppr = p.find(qn("w:pPr"))
    rpr = ppr.find(qn("w:rPr")) if ppr is not None else None
    if rpr is None:
        return False
    return rpr.find(qn("w:del")) is not None or rpr.find(qn("w:moveFrom")) is not None


def _mark_state(p: etree._Element) -> tuple[bool, bool]:
    ppr = p.find(qn("w:pPr"))
    rpr = ppr.find(qn("w:rPr")) if ppr is not None else None
    if rpr is None:
        return False, False
    return rpr.find(qn("w:ins")) is not None, rpr.find(qn("w:moveTo")) is not None


def _title_of(text: str, after: int) -> str:
    """Clause titles are the leading sentence fragment: ``Governing Law. ...``."""
    rest = text[after:].lstrip(" . \t")
    head = rest.split(".", 1)[0].strip()
    if 0 < len(head) <= 80 and head == head.strip():
        return head
    return rest[:60].strip()


def parse_clause(p: etree._Element) -> Clause | None:
    """Read a paragraph's clause number, or ``None`` if it is not numbered."""
    text = paragraph_text(p)
    match = CLAUSE_RE.match(text) or SECTION_RE.match(text)
    if match is None:
        return None
    label = match.group(1)
    inserted, moved = _mark_state(p)
    return Clause(
        p=p,
        label=label,
        number=tuple(int(part) for part in label.split(".")),
        span=(match.start(1), match.end(1)),
        title=_title_of(text, match.end(0)),
        inserted=inserted,
        moved=moved,
    )


class ClauseTree:
    """The document's numbered clauses, nested by level and kept in body order."""

    def __init__(self, root: etree._Element) -> None:
        self.root = root
        self.sections: list[Clause] = []
        #: labels carried by more than one clause right now.  A freshly inserted
        #: clause legitimately borrows its neighbour's number until the
        #: renumbering pass rewrites it, so this is a transient state to report,
        #: not an error -- but callers must not resolve blindly through it.
        self.duplicates: set[str] = set()
        self.reload()

    # -- build ----------------------------------------------------------
    def reload(self) -> ClauseTree:
        self.sections = []
        self.duplicates = set()
        seen: set[str] = set()
        stack: list[Clause] = []
        for p in self.root.iter(qn("w:p")):
            if _is_removed_paragraph(p):
                continue  # already struck: it is on its way out, ignore for numbering
            clause = parse_clause(p)
            if clause is None:
                continue
            if clause.label in seen:
                self.duplicates.add(clause.label)
            seen.add(clause.label)
            while stack and len(stack[-1].number) >= len(clause.number):
                stack.pop()
            if stack:
                clause.parent = stack[-1]
                stack[-1].children.append(clause)
            else:
                self.sections.append(clause)
            stack.append(clause)
        return self

    # -- lookup ---------------------------------------------------------
    def __iter__(self) -> Iterator[Clause]:
        for section in self.sections:
            yield from section.walk()

    def all(self) -> list[Clause]:
        return list(self)

    def get(self, label: str) -> Clause:
        """Resolve a clause number, preferring the one that was already there.

        An ``insert_clause`` borrows its neighbour's number until the renumbering
        pass rewrites it, so during a run two clauses can share a label.  A plain
        first-match-wins scan would then hand later actions the *new* clause --
        silently retargeting an edit the reviewer meant for the original.
        """
        first: Clause | None = None
        for clause in self:
            if clause.label != label:
                continue
            if not (clause.inserted or clause.moved):
                return clause
            if first is None:
                first = clause
        if first is not None:
            return first
        raise ClauseError(f"no clause numbered {label!r} in the document")

    def find(self, label: str) -> Clause | None:
        try:
            return self.get(label)
        except ClauseError:
            return None

    def siblings_of(self, clause: Clause) -> list[Clause]:
        return clause.parent.children if clause.parent else self.sections

    def snapshot(self) -> LabelSnapshot:
        """Freeze today's numbering so renumbering can diff against it."""
        return LabelSnapshot(self)

    # -- structural edits (tree only; the caller moves the XML) ----------
    def detach(self, clause: Clause) -> None:
        self.siblings_of(clause).remove(clause)

    def insert_after(self, clause: Clause, anchor: Clause) -> None:
        """Place ``clause`` directly after ``anchor`` among ``anchor``'s siblings."""
        siblings = self.siblings_of(anchor)
        clause.parent = anchor.parent
        siblings.insert(siblings.index(anchor) + 1, clause)

    def insert_as_child(self, clause: Clause, parent: Clause, index: int | None = None) -> None:
        clause.parent = parent
        if index is None:
            parent.children.append(clause)
        else:
            parent.children.insert(index, clause)

    # -- numbering ------------------------------------------------------
    def renumber(self, previous: LabelSnapshot) -> Renumbering:
        """Assign numbers from position and report every label that changed."""
        result = Renumbering()
        for section_index, section in enumerate(self.sections, start=1):
            self._apply_number(section, (section_index,), previous, result)
        return result

    def _apply_number(
        self,
        clause: Clause,
        number: tuple[int, ...],
        previous: LabelSnapshot,
        result: Renumbering,
    ) -> None:
        new_label = ".".join(str(part) for part in number)
        old_label = previous.get(clause.p, clause.label)
        result.claimed.add(old_label)
        clause.number = number
        if new_label != old_label:
            result.relabelled.append((clause, old_label, new_label))
            result.mapping[old_label] = new_label
        clause.label = new_label
        for child_index, child in enumerate(clause.children, start=1):
            self._apply_number(child, (*number, child_index), previous, result)


# ---------------------------------------------------------------------------
# cross-references
# ---------------------------------------------------------------------------
def iter_references(text: str) -> Iterator[tuple[int, int, str, str]]:
    """Yield ``(start, end, number, keyword)`` for each cross-reference in ``text``.

    Handles lists -- ``Sections 10.2 and 10.3``, ``Section 4.2, 4.3`` -- by
    walking number/joiner pairs after the introducing word, so every number in
    the run is reported separately and can be remapped on its own.
    """
    for word in _REF_WORD_RE.finditer(text):
        cursor = word.end()
        first = True
        while True:
            number = _REF_NUMBER_RE.match(text, cursor)
            if number is None:
                break
            yield number.start(1), number.end(1), number.group(1), word.group(1)
            cursor = number.end(1)
            first = False
            joiner = _REF_JOINER_RE.match(text, cursor)
            if joiner is None:
                break
            cursor = joiner.end()
        del first


def collect_reference_edits(
    root: etree._Element, mapping: dict[str, str], removed: Iterable[str] = ()
) -> tuple[list[ReferenceEdit], list[tuple[etree._Element, str]]]:
    """Find every cross-reference that ``mapping`` renames, plus dangling ones."""
    removed = set(removed)
    edits: list[ReferenceEdit] = []
    dangling: list[tuple[etree._Element, str]] = []
    for p in root.iter(qn("w:p")):
        if _is_removed_paragraph(p):
            continue
        text = paragraph_text(p)
        if not text:
            continue
        for start, end, number, keyword in iter_references(text):
            if number in removed:
                dangling.append((p, number))
                continue
            new = mapping.get(number)
            if new is None or new == number:
                continue
            edits.append(
                ReferenceEdit(
                    p=p,
                    start=start,
                    end=end,
                    old=number,
                    new=new,
                    context=f"{keyword} {number} -> {keyword} {new}",
                )
            )
    return edits, dangling


# ---------------------------------------------------------------------------
# rendering an outline for an LLM
# ---------------------------------------------------------------------------
def outline(tree: ClauseTree, body_chars: int = 240) -> list[dict]:
    """A compact, JSON-able view of the contract for prompting."""
    items = []
    for clause in tree:
        items.append(
            {
                "clause": clause.label,
                "level": clause.level,
                "title": clause.title,
                "text": clause.body[:body_chars],
            }
        )
    return items


def render_outline(
    tree: ClauseTree,
    body_chars: int = 400,
    clauses: Iterable[Clause] | None = None,
) -> str:
    """Numbered clauses, one per line, truncated to ``body_chars``.

    This is a *summary* view -- it drops everything unnumbered and caps each
    clause. For the text a reviewer actually has to read, use
    :func:`docx_redline.structure.segments.render_document`.
    """
    lines = []
    for clause in tree if clauses is None else clauses:
        indent = "  " * (clause.level - 1)
        lines.append(f"{indent}{clause.label}  {clause.body[:body_chars]}")
    return "\n".join(lines)
