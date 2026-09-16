# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Accept / reject / summarise tracked changes.

Accepting and rejecting is not just a convenience: it is how the test suite
proves the markup is *semantically* right.  A correct redline satisfies
``accept(redlined) == revised`` and ``reject(redlined) == original``.

Resolution is *selective*: :func:`accept` and :func:`reject` take an element
predicate, so a reviewer can take one revision and leave the rest as live
markup.  :func:`make_selector` builds that predicate from the ``w:id`` /
author / kind that :func:`summarize` reports.  ``select=None`` -- what
:func:`accept_all` and :func:`reject_all` pass -- means "every revision", and
takes a fast path that skips the bookkeeping entirely.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from lxml import etree

from ..oxml.edits import to_normal_text
from ..oxml.ns import qn

_P = qn("w:p")
_PPR = qn("w:pPr")
_TR = qn("w:tr")

#: ``*PrChange`` elements record a formatting revision; the *current* props are
#: already in the parent, so accepting just drops the record.
PR_CHANGE_TAGS = (
    "w:rPrChange",
    "w:pPrChange",
    "w:tblPrChange",
    "w:tblGridChange",
    "w:trPrChange",
    "w:tcPrChange",
    "w:sectPrChange",
)

#: Wrappers that carry revised *content* (as opposed to revised properties).
CONTENT_REVISION_TAGS = ("w:ins", "w:del", "w:moveFrom", "w:moveTo")

RANGE_MARKER_TAGS = (
    "w:moveFromRangeStart",
    "w:moveFromRangeEnd",
    "w:moveToRangeStart",
    "w:moveToRangeEnd",
    "w:customXmlInsRangeStart",
    "w:customXmlInsRangeEnd",
    "w:customXmlDelRangeStart",
    "w:customXmlDelRangeEnd",
    "w:customXmlMoveFromRangeStart",
    "w:customXmlMoveFromRangeEnd",
    "w:customXmlMoveToRangeStart",
    "w:customXmlMoveToRangeEnd",
)

_PR_CHANGE = frozenset(qn(t) for t in PR_CHANGE_TAGS)
_CONTENT = frozenset(qn(t) for t in CONTENT_REVISION_TAGS)
#: Everything a selector may be asked about -- what ``summarize`` reports.
_REVISIONS = _CONTENT | _PR_CHANGE
_MOVES = frozenset((qn("w:moveFrom"), qn("w:moveTo")))
_MOVE_STARTS = frozenset((qn("w:moveFromRangeStart"), qn("w:moveToRangeStart")))
_MOVE_ENDS = frozenset((qn("w:moveFromRangeEnd"), qn("w:moveToRangeEnd")))

#: A predicate over a revision element.  ``None`` stands for "all of them".
Selector = Callable[[etree._Element], bool]

#: ``kinds=`` shorthands that stand for a family of :attr:`Revision.kind`.
KIND_ALIASES = {
    "format": lambda kind: kind.startswith("format:"),
    "move": lambda kind: kind.startswith("move-"),
    "insert-any": lambda kind: kind.endswith("insert"),
    "delete-any": lambda kind: kind.endswith("delete"),
}


@dataclass
class Revision:
    kind: str
    author: str
    date: str
    text: str
    location: str
    #: The OOXML ``w:id`` of the revision element -- the handle ``accept(ids=...)``
    #: and ``reject(ids=...)`` select on.  Last so older positional calls still work.
    id: str = ""


@dataclass
class RevisionSummary:
    revisions: list[Revision] = field(default_factory=list)

    @property
    def counts(self) -> Counter:
        return Counter(r.kind for r in self.revisions)

    @property
    def authors(self) -> Counter:
        return Counter(r.author for r in self.revisions)

    @property
    def ids(self) -> list[str]:
        """Every ``w:id`` in report order -- feed a slice of these to ``accept``."""
        return [r.id for r in self.revisions if r.id]

    def by_id(self, rev_id: str | int) -> Revision | None:
        want = str(rev_id)
        return next((r for r in self.revisions if r.id == want), None)

    def __len__(self) -> int:
        return len(self.revisions)

    def format(self, limit: int | None = None) -> str:
        lines = [f"{len(self.revisions)} tracked change(s)"]
        for kind, count in sorted(self.counts.items()):
            lines.append(f"  {kind:<22} {count}")
        if self.authors:
            lines.append("  authors: " + ", ".join(f"{a} ({n})" for a, n in self.authors.items()))
        shown = self.revisions if limit is None else self.revisions[:limit]
        if shown:
            lines.append("")
            for rev in shown:
                snippet = rev.text.replace("\n", " ")
                if len(snippet) > 90:
                    snippet = snippet[:87] + "..."
                tag = f"#{rev.id} " if rev.id else ""
                lines.append(f"  {tag}[{rev.kind}] {rev.location}: {snippet}")
            if limit is not None and len(self.revisions) > limit:
                lines.append(f"  ... and {len(self.revisions) - limit} more")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


def kind_of(el: etree._Element) -> str | None:
    """The :attr:`Revision.kind` for a revision element, or ``None`` if it isn't one."""
    tag = el.tag
    if tag in (qn("w:ins"), qn("w:del")):
        base = "insert" if tag == qn("w:ins") else "delete"
        parent = el.getparent()
        holder = None if parent is None else parent.tag
        if holder == qn("w:trPr"):
            return f"row-{base}"
        if holder == qn("w:rPr"):
            return f"paragraph-mark-{base}"
        return base
    if tag == qn("w:moveFrom"):
        return "move-from"
    if tag == qn("w:moveTo"):
        return "move-to"
    if tag in _PR_CHANGE:
        return "format:" + tag.split("}")[1]
    return None


def revision_of(el: etree._Element, part: str = "document") -> Revision | None:
    """Describe a revision element, or ``None`` when ``el`` is not a revision."""
    kind = kind_of(el)
    if kind is None:
        return None
    return Revision(
        kind=kind,
        author=el.get(qn("w:author")) or "",
        date=el.get(qn("w:date")) or "",
        text="" if el.tag in _PR_CHANGE else _text_of(el),
        location=part,
        id=el.get(qn("w:id")) or "",
    )


def summarize(root: etree._Element, part: str = "document") -> RevisionSummary:
    summary = RevisionSummary()
    for el in root.iter():
        rev = revision_of(el, part)
        if rev is not None:
            summary.revisions.append(rev)
    return summary


def _text_of(el: etree._Element) -> str:
    parts = []
    for node in el.iter():
        if node.tag in (qn("w:t"), qn("w:delText")):
            parts.append(node.text or "")
        elif node.tag == qn("w:tab"):
            parts.append("\t")
        elif node.tag in (qn("w:br"), qn("w:cr")):
            parts.append("\n")
    return "".join(parts)


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def make_selector(
    ids=None,
    authors=None,
    kinds=None,
    where: Callable[[Revision], bool] | None = None,
    part: str = "document",
) -> Selector | None:
    """Build the predicate :func:`accept` / :func:`reject` filter on.

    Criteria combine with AND; the values inside one criterion combine with OR,
    so ``ids={"7", "8"}, authors="Legal"`` means "revision 7 or 8, provided
    Legal made it".  Each of ``ids`` / ``authors`` / ``kinds`` takes a single
    value or any iterable of them.  ``where`` gets the whole :class:`Revision`
    for anything the three cannot express.

    ``kinds`` matches :attr:`Revision.kind` exactly, or one of the
    :data:`KIND_ALIASES` families (``"format"``, ``"move"``, ``"insert-any"``,
    ``"delete-any"``).

    Returns ``None`` when nothing is constrained, which every resolver reads as
    "all of them" -- so ``accept(root, make_selector())`` is ``accept_all``.
    """
    ids = _as_set(ids)
    authors = _as_set(authors)
    kinds = _as_set(kinds)
    if not (ids or authors or kinds or where):
        return None

    def select(el: etree._Element) -> bool:
        # Cheap attribute tests first: `where` is the only criterion that needs
        # the revision text, and extracting it for every element of a 300-page
        # redline is not free.
        if ids and (el.get(qn("w:id")) or "") not in ids:
            return False
        if authors and (el.get(qn("w:author")) or "") not in authors:
            return False
        if kinds and not _kind_matches(kind_of(el) or "", kinds):
            return False
        if where is None:
            return True
        # Range markers are not revisions but do carry an id/author, and naming
        # one is a natural way to ask for the move it delimits.
        return where(
            revision_of(el, part)
            or Revision(
                kind="",
                author=el.get(qn("w:author")) or "",
                date=el.get(qn("w:date")) or "",
                text="",
                location=part,
                id=el.get(qn("w:id")) or "",
            )
        )

    return select


def _as_set(value) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, (str, bytes, int)):
        value = [value]
    return frozenset(str(v) for v in value)


def _kind_matches(kind: str, kinds: frozenset[str]) -> bool:
    if kind in kinds:
        return True
    return any(alias in kinds and test(kind) for alias, test in KIND_ALIASES.items())


def _plan(root: etree._Element, select: Selector | None):
    """Turn ``select`` into the element set to resolve, plus the moves it covers.

    ``(None, None)`` means "everything" -- the fast path ``accept_all`` takes.

    Resolving one half of a move would duplicate or lose the moved text, so a
    hit on either half, or on the range marker naming it, pulls in the other.
    """
    if select is None:
        return None, None
    covering = _move_paragraphs(root)
    chosen: set[etree._Element] = set()
    names: set[str] = set()
    for el in root.iter():
        if el.tag in _REVISIONS:
            if select(el):
                chosen.add(el)
                if el.tag in _MOVES:
                    names |= covering.get(_enclosing_p(el), frozenset())
        elif el.tag in _MOVE_STARTS and select(el):
            name = el.get(qn("w:name"))
            if name:
                names.add(name)
    for paragraph, covered in covering.items():
        if covered & names:
            chosen.update(el for el in paragraph.iter() if el.tag in _MOVES)
    return chosen, names


def _move_paragraphs(root: etree._Element) -> dict[etree._Element, frozenset[str]]:
    """Map each paragraph to the names of the move ranges covering it.

    A range may span several paragraphs, and the moved paragraph *mark* sits in
    ``w:pPr`` -- ahead of the range start in document order -- so membership is
    tracked per paragraph rather than per element.
    """
    open_ranges: dict[str, str] = {}
    covering: dict[etree._Element, frozenset[str]] = {}
    for paragraph in root.iter(_P):
        names = set(open_ranges.values())
        for el in paragraph.iter():
            if el.tag in _MOVE_STARTS:
                name = el.get(qn("w:name"))
                if name:
                    open_ranges[el.get(qn("w:id")) or name] = name
                    names.add(name)
            elif el.tag in _MOVE_ENDS:
                name = open_ranges.pop(el.get(qn("w:id")) or "\0", None)
                if name:
                    names.add(name)
        if names:
            covering[paragraph] = frozenset(names)
    return covering


def _enclosing_p(el: etree._Element) -> etree._Element | None:
    node = el.getparent()
    while node is not None and node.tag != _P:
        node = node.getparent()
    return node


def _picked(chosen: set | None, el: etree._Element) -> bool:
    return chosen is None or el in chosen


# ---------------------------------------------------------------------------
# accept / reject
# ---------------------------------------------------------------------------


def accept(root: etree._Element, select: Selector | None = None) -> None:
    """Apply the selected tracked changes; unselected ones stay live markup."""
    _resolve(root, keep_inserted=True, select=select)


def reject(root: etree._Element, select: Selector | None = None) -> None:
    """Discard the selected tracked changes; unselected ones stay live markup."""
    _resolve(root, keep_inserted=False, select=select)


def accept_all(root: etree._Element) -> None:
    """Apply every tracked change, leaving clean XML."""
    accept(root)


def reject_all(root: etree._Element) -> None:
    """Discard every tracked change, restoring the pre-redline document."""
    reject(root)


def _resolve(root: etree._Element, keep_inserted: bool, select: Selector | None = None) -> None:
    chosen, moves = _plan(root, select)
    _drop_pr_changes(root, revert=not keep_inserted, chosen=chosen)
    _resolve_content(root, keep_inserted, chosen)
    _resolve_rows(root, keep_inserted, chosen)
    # Range markers must go before paragraph marks are resolved, otherwise an
    # emptied move-destination paragraph still looks like it has content.
    _drop_range_markers(root, moves)
    _resolve_paragraph_marks(root, keep_inserted, chosen)


def _drop_pr_changes(root: etree._Element, revert: bool, chosen: set | None = None) -> None:
    """Remove ``*PrChange`` records; on reject, restore the baseline they carry."""
    for change in [el for el in root.iter() if el.tag in _PR_CHANGE and _picked(chosen, el)]:
        parent = change.getparent()  # the w:rPr / w:pPr / w:trPr ... being changed
        if parent is None:
            continue
        if not (revert and len(change)):
            parent.remove(change)
            continue
        grandparent = parent.getparent()
        if grandparent is None:
            parent.remove(change)
            continue
        baseline = change[0]
        baseline.tag = parent.tag
        # A *PrChange baseline is a *base* type: it deliberately omits members
        # that are not formatting (the paragraph-mark rPr, section properties,
        # row ins/del markers).  Those must survive a reject.
        for keep_tag in ("w:ins", "w:del", "w:moveFrom", "w:moveTo", "w:rPr", "w:sectPr"):
            for node in parent.findall(qn(keep_tag)):
                parent.remove(node)
                baseline.append(node)
        _reorder_baseline(baseline)
        if len(baseline):
            grandparent.replace(parent, baseline)
        else:
            grandparent.remove(parent)  # the pre-edit state had no properties


def _reorder_baseline(baseline: etree._Element) -> None:
    """Re-sort carried-over children into schema order for the parent type."""
    from ..oxml.elements import PPR_ORDER, TRPR_ORDER, insert_in_order

    order = {qn("w:pPr"): PPR_ORDER, qn("w:trPr"): TRPR_ORDER}.get(baseline.tag)
    if not order:
        return
    children = list(baseline)
    for child in children:
        baseline.remove(child)
    for child in children:
        insert_in_order(baseline, child, order)


def _resolve_content(root: etree._Element, keep_inserted: bool, chosen: set | None = None) -> None:
    """Unwrap or drop ``w:ins`` / ``w:del`` / ``w:moveFrom`` / ``w:moveTo``."""
    keep_tags = {qn("w:ins"), qn("w:moveTo")} if keep_inserted else {qn("w:del"), qn("w:moveFrom")}
    drop_tags = {qn("w:del"), qn("w:moveFrom")} if keep_inserted else {qn("w:ins"), qn("w:moveTo")}

    # innermost first so nested <w:ins><w:del>...</w:del></w:ins> resolves correctly
    nodes = [el for el in root.iter() if el.tag in keep_tags | drop_tags and _picked(chosen, el)]
    for el in reversed(nodes):
        parent = el.getparent()
        if parent is None or parent.tag in (qn("w:rPr"), qn("w:trPr")):
            continue  # paragraph-mark / row markers handled separately
        if el.tag in drop_tags:
            parent.remove(el)
        else:
            index = parent.index(el)
            for offset, child in enumerate(list(el)):
                el.remove(child)
                parent.insert(index + offset, child)
                if child.tag == qn("w:r"):
                    to_normal_text(child)
            parent.remove(el)


def _resolve_rows(root: etree._Element, keep_inserted: bool, chosen: set | None = None) -> None:
    for tr in list(root.iter(_TR)):
        trpr = tr.find(qn("w:trPr"))
        if trpr is None:
            continue
        ins = trpr.find(qn("w:ins"))
        dele = trpr.find(qn("w:del"))
        if not _picked(chosen, ins):
            ins = None
        if not _picked(chosen, dele):
            dele = None
        if chosen is not None and ins is None and dele is None:
            continue  # nothing selected here -- leave the row exactly as it is
        if ins is not None:
            if keep_inserted:
                trpr.remove(ins)
            else:
                tr.getparent().remove(tr)
                continue
        if dele is not None:
            if keep_inserted:
                tr.getparent().remove(tr)
                continue
            trpr.remove(dele)
        if not len(trpr):
            tr.remove(trpr)


def _resolve_paragraph_marks(
    root: etree._Element, keep_inserted: bool, chosen: set | None = None
) -> None:
    """Handle ¶-mark revisions, which merge or split paragraphs when resolved."""
    for p in list(root.iter(_P)):
        ppr = p.find(_PPR)
        if ppr is None:
            continue
        rpr = ppr.find(qn("w:rPr"))
        if rpr is None:
            continue
        markers = [
            el
            for el in (rpr.find(qn(t)) for t in ("w:ins", "w:del", "w:moveFrom", "w:moveTo"))
            if el is not None and _picked(chosen, el)
        ]
        if chosen is not None and not markers:
            continue  # nothing selected here -- leave the mark exactly as it is
        tags = {el.tag for el in markers}
        # A moved paragraph's mark behaves exactly like an insert (at the
        # destination) or a delete (at the source).
        inserted = bool(tags & {qn("w:ins"), qn("w:moveTo")})
        deleted = bool(tags & {qn("w:del"), qn("w:moveFrom")})
        removes_mark = (deleted and keep_inserted) or (inserted and not keep_inserted)
        for found in markers:
            rpr.remove(found)
        if not len(rpr):
            ppr.remove(rpr)
        if not len(ppr):
            p.remove(ppr)
        if removes_mark:
            # Rejecting an *inserted* mark undoes a split this redline made, so
            # the paragraph it created must not outlive it even when there is
            # nothing after it to merge into.
            _merge_with_next(p, backward=inserted and not keep_inserted)


def _merge_with_next(p: etree._Element, backward: bool = False) -> None:
    """Delete ``p``'s paragraph mark: its content joins the following paragraph."""
    parent = p.getparent()
    if parent is None:
        return
    nxt = p.getnext()
    if nxt is None or nxt.tag != _P:
        # Nothing to merge into (last paragraph of a cell/body, or a table comes
        # next).  Keeping the now-empty paragraph is what Word does too -- except
        # for a paragraph this redline added, where the split itself is what is
        # being undone and leaving the husk behind would not restore the original.
        prev = p.getprevious() if backward else None
        if prev is not None and prev.tag == _P:
            for child in [c for c in p if c.tag != _PPR]:
                p.remove(child)
                prev.append(child)
            parent.remove(p)
        elif not _has_content(p):
            parent.remove(p)
        return
    moving = [c for c in p if c.tag != _PPR]
    target_ppr = nxt.find(_PPR)
    anchor = 0 if target_ppr is None else 1
    for offset, child in enumerate(moving):
        p.remove(child)
        nxt.insert(anchor + offset, child)
    parent.remove(p)


#: Elements that carry no visible text and so do not keep a paragraph alive.
_INERT = {
    qn("w:pPr"),
    qn("w:bookmarkStart"),
    qn("w:bookmarkEnd"),
    qn("w:proofErr"),
    qn("w:commentRangeStart"),
    qn("w:commentRangeEnd"),
}


def _has_content(p: etree._Element) -> bool:
    return any(c.tag not in _INERT for c in p)


def _drop_range_markers(root: etree._Element, moves: set[str] | None = None) -> None:
    """Remove range markers -- but only for the moves a selective resolve took."""
    if moves is None:
        wanted = {qn(t) for t in RANGE_MARKER_TAGS}
        victims = [e for e in root.iter() if e.tag in wanted]
    elif not moves:
        return
    else:
        ids = {
            el.get(qn("w:id"))
            for el in root.iter()
            if el.tag in _MOVE_STARTS and (el.get(qn("w:name")) or "") in moves
        }
        ids.discard(None)
        victims = [
            e
            for e in root.iter()
            if e.tag in _MOVE_STARTS | _MOVE_ENDS and e.get(qn("w:id")) in ids
        ]
    for el in victims:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
