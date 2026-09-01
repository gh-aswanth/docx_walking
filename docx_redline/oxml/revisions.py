# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Revision identity: author, timestamp and the document-unique ``w:id`` pool."""

from __future__ import annotations

import datetime as _dt
import itertools
import re
from dataclasses import dataclass, field

from lxml import etree

from .ns import qn

#: Every element that carries a revision ``w:id`` that must be unique per document.
REVISION_TAGS = (
    "w:ins",
    "w:del",
    "w:moveFrom",
    "w:moveTo",
    "w:moveFromRangeStart",
    "w:moveFromRangeEnd",
    "w:moveToRangeStart",
    "w:moveToRangeEnd",
    "w:rPrChange",
    "w:pPrChange",
    "w:tblPrChange",
    "w:tblGridChange",
    "w:trPrChange",
    "w:tcPrChange",
    "w:sectPrChange",
    "w:numberingChange",
    "w:cellIns",
    "w:cellDel",
    "w:cellMerge",
    "w:customXmlInsRangeStart",
    "w:customXmlDelRangeStart",
)

_ISO = "%Y-%m-%dT%H:%M:%SZ"


def utc_stamp(when: _dt.datetime | str | None = None) -> str:
    """Normalise a datetime to the ``w:date`` format Word expects (UTC, ISO-8601)."""
    if isinstance(when, str):
        return when
    if when is None:
        when = _dt.datetime.now(_dt.UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.UTC)
    return when.astimezone(_dt.UTC).strftime(_ISO)


def initials_for(name: str) -> str:
    parts = [p for p in re.split(r"[^\w]+", name or "") if p]
    if not parts:
        return "R"
    return "".join(p[0].upper() for p in parts[:3])


@dataclass
class Author:
    """Who the revision is attributed to."""

    name: str = "Redline"
    initials: str | None = None
    date: str | None = None

    def __post_init__(self) -> None:
        if not self.initials:
            self.initials = initials_for(self.name)
        self.date = utc_stamp(self.date)


class RevisionIds:
    """Allocates ``w:id`` values that do not collide with ones already in the file.

    Word tolerates duplicates but some downstream tooling (and Word's own
    "reject" logic for grouped revisions) does not, so we scan every part once
    and then hand out a monotonically increasing sequence.
    """

    def __init__(self, start: int = 1) -> None:
        self._counter = itertools.count(start)

    @classmethod
    def from_elements(cls, elements) -> RevisionIds:
        highest = 0
        wanted = {qn(t) for t in REVISION_TAGS}
        for root in elements:
            if root is None:
                continue
            for el in root.iter():
                if el.tag in wanted:
                    raw = el.get(qn("w:id"))
                    if raw and raw.lstrip("-").isdigit():
                        highest = max(highest, int(raw))
        return cls(highest + 1)

    def next(self) -> str:
        return str(next(self._counter))


@dataclass
class RevisionContext:
    """Bundles author + id pool; every mutation helper takes one of these."""

    author: Author = field(default_factory=Author)
    ids: RevisionIds = field(default_factory=RevisionIds)

    def stamp(self, el: etree._Element) -> etree._Element:
        """Apply ``w:id`` / ``w:author`` / ``w:date`` to a revision element."""
        el.set(qn("w:id"), self.ids.next())
        el.set(qn("w:author"), self.author.name)
        el.set(qn("w:date"), self.author.date)
        return el
