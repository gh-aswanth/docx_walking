# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Accept / reject / summarise tracked changes.

Accepting and rejecting is not just a convenience: it is how the test suite
proves the markup is *semantically* right.  A correct redline satisfies
``accept(redlined) == revised`` and ``reject(redlined) == original``.
"""

from __future__ import annotations

from collections import Counter
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


@dataclass
class Revision:
    kind: str
    author: str
    date: str
    text: str
    location: str


@dataclass
class RevisionSummary:
    revisions: list[Revision] = field(default_factory=list)

    @property
    def counts(self) -> Counter:
        return Counter(r.kind for r in self.revisions)

    @property
    def authors(self) -> Counter:
        return Counter(r.author for r in self.revisions)

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
                lines.append(f"  [{rev.kind}] {rev.location}: {snippet}")
            if limit is not None and len(self.revisions) > limit:
                lines.append(f"  ... and {len(self.revisions) - limit} more")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


def summarize(root: etree._Element, part: str = "document") -> RevisionSummary:
    summary = RevisionSummary()
    for el in root.iter():
        tag = el.tag
        author = el.get(qn("w:author")) or ""
        date = el.get(qn("w:date")) or ""
        if tag == qn("w:ins"):
            kind = "paragraph-mark-insert" if el.getparent().tag == qn("w:rPr") else "insert"
            if el.getparent().tag == qn("w:trPr"):
                kind = "row-insert"
            summary.revisions.append(Revision(kind, author, date, _text_of(el), part))
        elif tag == qn("w:del"):
            kind = "paragraph-mark-delete" if el.getparent().tag == qn("w:rPr") else "delete"
            if el.getparent().tag == qn("w:trPr"):
                kind = "row-delete"
            summary.revisions.append(Revision(kind, author, date, _text_of(el), part))
        elif tag == qn("w:moveFrom"):
            summary.revisions.append(Revision("move-from", author, date, _text_of(el), part))
        elif tag == qn("w:moveTo"):
            summary.revisions.append(Revision("move-to", author, date, _text_of(el), part))
        elif tag in {qn(t) for t in PR_CHANGE_TAGS}:
            name = tag.split("}")[1]
            summary.revisions.append(Revision(f"format:{name}", author, date, "", part))
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
# accept / reject
# ---------------------------------------------------------------------------


def accept_all(root: etree._Element) -> None:
    """Apply every tracked change, leaving clean XML."""
    _resolve(root, keep_inserted=True)


def reject_all(root: etree._Element) -> None:
    """Discard every tracked change, restoring the pre-redline document."""
    _resolve(root, keep_inserted=False)


def _resolve(root: etree._Element, keep_inserted: bool) -> None:
    _drop_pr_changes(root, revert=not keep_inserted)
    _resolve_content(root, keep_inserted)
    _resolve_rows(root, keep_inserted)
    # Range markers must go before paragraph marks are resolved, otherwise an
    # emptied move-destination paragraph still looks like it has content.
    _drop_range_markers(root)
    _resolve_paragraph_marks(root, keep_inserted)


def _drop_pr_changes(root: etree._Element, revert: bool) -> None:
    """Remove ``*PrChange`` records; on reject, restore the baseline they carry."""
    wanted = {qn(t) for t in PR_CHANGE_TAGS}
    for change in [el for el in root.iter() if el.tag in wanted]:
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


def _resolve_content(root: etree._Element, keep_inserted: bool) -> None:
    """Unwrap or drop ``w:ins`` / ``w:del`` / ``w:moveFrom`` / ``w:moveTo``."""
    keep_tags = {qn("w:ins"), qn("w:moveTo")} if keep_inserted else {qn("w:del"), qn("w:moveFrom")}
    drop_tags = {qn("w:del"), qn("w:moveFrom")} if keep_inserted else {qn("w:ins"), qn("w:moveTo")}

    # innermost first so nested <w:ins><w:del>...</w:del></w:ins> resolves correctly
    nodes = [el for el in root.iter() if el.tag in keep_tags | drop_tags]
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


def _resolve_rows(root: etree._Element, keep_inserted: bool) -> None:
    for tr in list(root.iter(_TR)):
        trpr = tr.find(qn("w:trPr"))
        if trpr is None:
            continue
        ins = trpr.find(qn("w:ins"))
        dele = trpr.find(qn("w:del"))
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


def _resolve_paragraph_marks(root: etree._Element, keep_inserted: bool) -> None:
    """Handle ¶-mark revisions, which merge or split paragraphs when resolved."""
    for p in list(root.iter(_P)):
        ppr = p.find(_PPR)
        if ppr is None:
            continue
        rpr = ppr.find(qn("w:rPr"))
        if rpr is None:
            continue
        # A moved paragraph's mark behaves exactly like an insert (at the
        # destination) or a delete (at the source).
        ins = (
            rpr.find(qn("w:ins")) if rpr.find(qn("w:ins")) is not None else rpr.find(qn("w:moveTo"))
        )
        dele = (
            rpr.find(qn("w:del"))
            if rpr.find(qn("w:del")) is not None
            else rpr.find(qn("w:moveFrom"))
        )
        removes_mark = (dele is not None and keep_inserted) or (
            ins is not None and not keep_inserted
        )
        for marker in ("w:ins", "w:del", "w:moveFrom", "w:moveTo"):
            found = rpr.find(qn(marker))
            if found is not None:
                rpr.remove(found)
        if not len(rpr):
            ppr.remove(rpr)
        if not len(ppr):
            p.remove(ppr)
        if removes_mark:
            _merge_with_next(p)


def _merge_with_next(p: etree._Element) -> None:
    """Delete ``p``'s paragraph mark: its content joins the following paragraph."""
    parent = p.getparent()
    if parent is None:
        return
    nxt = p.getnext()
    if nxt is None or nxt.tag != _P:
        # Nothing to merge into (last paragraph of a cell/body).  Keeping the
        # now-empty paragraph is what Word does too.
        if not _has_content(p):
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


def _drop_range_markers(root: etree._Element) -> None:
    wanted = {qn(t) for t in RANGE_MARKER_TAGS}
    for el in [e for e in root.iter() if e.tag in wanted]:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
