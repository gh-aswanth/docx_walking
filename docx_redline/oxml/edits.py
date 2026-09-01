# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""The tracked-change primitives: insert / delete / format, at run granularity.

Everything here works on raw ``lxml`` elements so it can be reused for body
paragraphs, table cells, headers, footers and footnotes alike.
"""

from __future__ import annotations

import copy

from lxml import etree

from .elements import (
    PARA_RPR_ORDER,
    PPR_ORDER,
    TRPR_ORDER,
    clone_shell,
    deepcopy_without,
    get_or_add,
    insert_in_order,
    make,
    make_run,
)
from .ns import qn
from .revisions import RevisionContext
from .textmap import ParagraphText, iter_visible_runs, split_at

_INS = qn("w:ins")
_DEL = qn("w:del")
_MOVE_TO = qn("w:moveTo")
_MOVE_FROM = qn("w:moveFrom")
_RUN = qn("w:r")
_T = qn("w:t")
_INSTRTEXT = qn("w:instrText")

#: Wrappers that may not legally contain another ``w:ins``.
_NON_NESTABLE = {_INS, _MOVE_TO}


# ---------------------------------------------------------------------------
# deletion
# ---------------------------------------------------------------------------


def to_deleted_text(run: etree._Element) -> None:
    """Rewrite a run's text nodes for a deletion (``w:t`` -> ``w:delText``)."""
    for child in list(run):
        if child.tag == _T:
            child.tag = qn("w:delText")
        elif child.tag == _INSTRTEXT:
            child.tag = qn("w:delInstrText")


def to_normal_text(run: etree._Element) -> None:
    """Inverse of :func:`to_deleted_text`, used when rejecting a deletion."""
    for child in list(run):
        if child.tag == qn("w:delText"):
            child.tag = _T
        elif child.tag == qn("w:delInstrText"):
            child.tag = _INSTRTEXT


def mark_runs_deleted(runs, ctx: RevisionContext) -> list[etree._Element]:
    """Wrap ``runs`` in ``w:del``, grouping runs that share a parent.

    Runs already inside a ``w:ins`` get a ``w:del`` *nested inside* that
    ``w:ins`` -- the OOXML idiom for "this insertion was later deleted".
    """
    created: list[etree._Element] = []
    group: list[etree._Element] = []
    for run in list(runs):
        if group and (
            run.getparent() is not group[-1].getparent() or group[-1].getnext() is not run
        ):
            created.append(_wrap_group(group, "w:del", ctx))
            group = []
        group.append(run)
    if group:
        created.append(_wrap_group(group, "w:del", ctx))
    return created


def _wrap_group(runs, tag: str, ctx: RevisionContext) -> etree._Element:
    parent = runs[0].getparent()
    wrapper = ctx.stamp(make(tag))
    parent.insert(parent.index(runs[0]), wrapper)
    for run in runs:
        parent.remove(run)
        wrapper.append(run)
        if tag in ("w:del", "w:moveFrom"):
            to_deleted_text(run)
    return wrapper


def delete_range(
    p: etree._Element, start: int, end: int, ctx: RevisionContext
) -> list[etree._Element]:
    """Mark characters ``[start, end)`` of paragraph ``p`` as deleted."""
    if end <= start:
        return []
    split_at(p, end)
    split_at(p, start)
    view = ParagraphText(p)
    runs = view.runs_in(start, end)
    return mark_runs_deleted(runs, ctx)


# ---------------------------------------------------------------------------
# insertion
# ---------------------------------------------------------------------------


def insertion_point(p: etree._Element, offset: int) -> tuple[etree._Element, int]:
    """Return ``(parent, index)`` at which a ``w:ins`` for ``offset`` belongs."""
    view = ParagraphText(p)
    if offset >= len(view):
        if view.segments:
            run = view.segments[-1].run
            parent = run.getparent()
            index = parent.index(run) + 1
        else:
            parent, index = p, len(p)
    else:
        split_at(p, offset)
        view.refresh()
        seg = next((s for s in view.segments if s.start == offset), None)
        if seg is None:  # pragma: no cover - defensive
            parent, index = p, len(p)
        else:
            parent = seg.run.getparent()
            index = parent.index(seg.run)
    return _escape_non_nestable(p, parent, index)


def _escape_non_nestable(p, parent, index):
    """Hoist an insertion point out of a ``w:ins``/``w:moveTo`` wrapper.

    ``<w:ins>`` may not nest, so when the target position falls inside one we
    split that wrapper in two and aim between the halves.
    """
    while parent is not p and parent.tag in _NON_NESTABLE:
        grandparent = parent.getparent()
        tail_children = list(parent)[index:]
        if not tail_children:
            index = grandparent.index(parent) + 1
        elif index == 0:
            index = grandparent.index(parent)
        else:
            tail = clone_shell(parent)
            tail.set(qn("w:id"), ctx_free_id(parent))
            for child in tail_children:
                parent.remove(child)
                tail.append(child)
            parent.addnext(tail)
            index = grandparent.index(tail)
        parent = grandparent
    return parent, index


def ctx_free_id(el: etree._Element) -> str:
    """Derive a distinct-enough id for a wrapper clone (kept out of the pool)."""
    raw = el.get(qn("w:id")) or "1"
    try:
        return str(int(raw) + 900000)
    except ValueError:  # pragma: no cover
        return raw


def insert_runs(p: etree._Element, offset: int, runs, ctx: RevisionContext) -> etree._Element:
    """Insert ``runs`` at ``offset`` wrapped in a tracked ``w:ins``."""
    parent, index = insertion_point(p, offset)
    wrapper = ctx.stamp(make("w:ins"))
    for run in runs:
        wrapper.append(run)
    parent.insert(index, wrapper)
    return wrapper


def insert_text(
    p: etree._Element,
    offset: int,
    text: str,
    ctx: RevisionContext,
    rpr: etree._Element | None = None,
) -> etree._Element:
    if rpr is None:
        rpr = nearest_rpr(p, offset)
    return insert_runs(p, offset, [make_run(text, rpr)], ctx)


def nearest_rpr(p: etree._Element, offset: int) -> etree._Element | None:
    """Character formatting to copy for text inserted at ``offset``."""
    view = ParagraphText(p)
    candidate = None
    for seg in view.segments:
        candidate = seg.run
        if seg.end >= offset:
            break
    if candidate is None:
        for run in iter_visible_runs(p):
            candidate = run
            break
    if candidate is None:
        return None
    rpr = candidate.find(qn("w:rPr"))
    return copy.deepcopy(rpr) if rpr is not None else None


def replace_range(
    p: etree._Element,
    start: int,
    end: int,
    text: str,
    ctx: RevisionContext,
    insertion_first: bool = False,
) -> None:
    """Strike ``[start, end)`` and insert ``text`` in its place.

    ``insertion_first`` controls the on-screen order of the pair; the default
    (and Word's own Compare output) is struck-out text followed by the
    replacement.
    """
    rpr = nearest_rpr(p, start)
    if insertion_first:
        if text:
            insert_text(p, start, text, ctx, rpr)
            # The inserted text is now part of the visible flow, so the range
            # that still has to be struck has shifted right by its length.
            shift = len(text)
            delete_range(p, start + shift, end + shift, ctx)
        else:
            delete_range(p, start, end, ctx)
        return

    deleted = delete_range(p, start, end, ctx)
    if not text:
        return
    if deleted:
        anchor = deleted[-1]
        parent = anchor.getparent()
        wrapper = ctx.stamp(make("w:ins"))
        wrapper.append(make_run(text, rpr))
        parent.insert(parent.index(anchor) + 1, wrapper)
    else:
        insert_text(p, start, text, ctx, rpr)


# ---------------------------------------------------------------------------
# paragraph-level marks
# ---------------------------------------------------------------------------


def _para_rpr(p: etree._Element) -> etree._Element:
    ppr = get_or_add(p, "w:pPr", ())
    if p.index(ppr) != 0:
        p.remove(ppr)
        p.insert(0, ppr)
    return get_or_add(ppr, "w:rPr", PPR_ORDER)


def mark_paragraph_mark(p: etree._Element, tag: str, ctx: RevisionContext) -> etree._Element:
    """Flag the paragraph *mark* (the ¶ itself) as inserted/deleted/moved."""
    rpr = _para_rpr(p)
    existing = rpr.find(qn(tag))
    if existing is not None:
        return existing
    el = ctx.stamp(make(tag))
    insert_in_order(rpr, el, PARA_RPR_ORDER)
    return el


def mark_paragraph_inserted(p: etree._Element, ctx: RevisionContext) -> None:
    """Whole paragraph is new: content in ``w:ins`` + inserted paragraph mark."""
    runs = list(iter_visible_runs(p))
    if runs:
        _wrap_group_all(runs, "w:ins", ctx)
    mark_paragraph_mark(p, "w:ins", ctx)


def mark_paragraph_deleted(p: etree._Element, ctx: RevisionContext) -> None:
    """Whole paragraph goes away: content struck + deleted paragraph mark."""
    runs = list(iter_visible_runs(p))
    if runs:
        mark_runs_deleted(runs, ctx)
    mark_paragraph_mark(p, "w:del", ctx)


def _wrap_group_all(runs, tag: str, ctx: RevisionContext) -> None:
    group: list[etree._Element] = []
    for run in runs:
        parent = run.getparent()
        if parent.tag in _NON_NESTABLE and tag == "w:ins":
            continue  # already inside an insertion
        if group and (
            run.getparent() is not group[-1].getparent() or group[-1].getnext() is not run
        ):
            _wrap_group(group, tag, ctx)
            group = []
        group.append(run)
    if group:
        _wrap_group(group, tag, ctx)


# ---------------------------------------------------------------------------
# table rows
# ---------------------------------------------------------------------------


def mark_row_inserted(tr: etree._Element, ctx: RevisionContext) -> None:
    trpr = get_or_add(tr, "w:trPr", ("w:tblPrEx", "w:trPr"))
    if tr.index(trpr) > 1:
        tr.remove(trpr)
        tr.insert(0, trpr)
    insert_in_order(trpr, ctx.stamp(make("w:ins")), TRPR_ORDER)
    for p in tr.iter(qn("w:p")):
        mark_paragraph_inserted(p, ctx)


def mark_row_deleted(tr: etree._Element, ctx: RevisionContext) -> None:
    trpr = get_or_add(tr, "w:trPr", ("w:tblPrEx", "w:trPr"))
    if tr.index(trpr) > 1:
        tr.remove(trpr)
        tr.insert(0, trpr)
    insert_in_order(trpr, ctx.stamp(make("w:del")), TRPR_ORDER)
    for p in tr.iter(qn("w:p")):
        runs = list(iter_visible_runs(p))
        if runs:
            mark_runs_deleted(runs, ctx)
        mark_paragraph_mark(p, "w:del", ctx)


# ---------------------------------------------------------------------------
# formatting revisions
# ---------------------------------------------------------------------------


def record_rpr_change(
    run: etree._Element, old_rpr: etree._Element | None, ctx: RevisionContext
) -> None:
    """Attach ``w:rPrChange`` carrying the pre-edit character formatting."""
    rpr = run.find(qn("w:rPr"))
    if rpr is None:
        rpr = make("w:rPr")
        run.insert(0, rpr)
    for stale in rpr.findall(qn("w:rPrChange")):
        rpr.remove(stale)
    change = ctx.stamp(make("w:rPrChange"))
    baseline = deepcopy_without(old_rpr, ("w:rPrChange",)) if old_rpr is not None else make("w:rPr")
    baseline.tag = qn("w:rPr")
    change.append(baseline)
    rpr.append(change)


def record_ppr_change(
    p: etree._Element, old_ppr: etree._Element | None, ctx: RevisionContext
) -> None:
    """Attach ``w:pPrChange``; the baseline is a CT_PPrBase (no rPr/sectPr)."""
    ppr = get_or_add(p, "w:pPr", ())
    if p.index(ppr) != 0:
        p.remove(ppr)
        p.insert(0, ppr)
    for stale in ppr.findall(qn("w:pPrChange")):
        ppr.remove(stale)
    change = ctx.stamp(make("w:pPrChange"))
    baseline = (
        deepcopy_without(old_ppr, ("w:rPr", "w:sectPr", "w:pPrChange"))
        if old_ppr is not None
        else make("w:pPr")
    )
    baseline.tag = qn("w:pPr")
    change.append(baseline)
    insert_in_order(ppr, change, PPR_ORDER)


# ---------------------------------------------------------------------------
# untracked surgery
# ---------------------------------------------------------------------------


def replace_in_place(p: etree._Element, start: int, end: int, text: str) -> bool:
    """Overwrite ``[start, end)`` with ``text`` *without* recording a revision.

    Only correct when the surrounding content is itself already a revision --
    renumbering the label of a clause that is wholly inside a ``w:ins`` or
    ``w:moveTo``.  Tracking an edit inside an insertion would show reviewers a
    strikeout on text that does not exist in the original document.
    """
    from .textmap import ParagraphText, split_at

    if end <= start:
        return False
    split_at(p, end)
    split_at(p, start)
    view = ParagraphText(p)
    runs = view.runs_in(start, end)
    if not runs:
        return False
    first = runs[0]
    parent = first.getparent()
    rpr = first.find(qn("w:rPr"))
    replacement = make_run(text, rpr)
    parent.insert(parent.index(first), replacement)
    for run in runs:
        run.getparent().remove(run)
    return True
