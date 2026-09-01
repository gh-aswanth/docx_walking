# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Low-level element construction and schema-order aware insertion."""

from __future__ import annotations

import copy

from docx.oxml.parser import oxml_parser
from lxml import etree

from .ns import NS, qn


def make(tag: str, **attrs) -> etree._Element:
    """Create a standalone element bound to python-docx's element classes.

    Going through ``oxml_parser`` (rather than plain ``etree.Element``) matters:
    it is what makes a new ``w:p`` come back as a ``CT_P``, so the result works
    with ``docx.text.paragraph.Paragraph`` and friends.
    """
    el = oxml_parser.makeelement(qn(tag), nsmap={"w": NS["w"]})
    for key, value in attrs.items():
        if value is None:
            continue
        el.set(qn(key), str(value))
    return el


def text_element(text: str, tag: str = "w:t") -> etree._Element:
    el = make(tag)
    el.text = text
    if text != text.strip() or text == "":
        el.set(qn("xml:space"), "preserve")
    return el


def make_run(text: str = "", rpr: etree._Element | None = None) -> etree._Element:
    """Build a ``w:r``. ``rpr`` is deep-copied so callers can reuse a template."""
    run = make("w:r")
    if rpr is not None:
        run.append(copy.deepcopy(rpr))
    if text:
        for i, chunk in enumerate(text.split("\n")):
            if i:
                run.append(make("w:br"))
            if chunk:
                run.append(text_element(chunk))
    return run


def get_or_add(parent: etree._Element, tag: str, order: tuple[str, ...] = ()) -> etree._Element:
    """Return ``parent``'s child ``tag``, creating it in schema position if absent."""
    found = parent.find(qn(tag))
    if found is not None:
        return found
    child = make(tag)
    insert_in_order(parent, child, order)
    return child


def insert_in_order(parent: etree._Element, child: etree._Element, order: tuple[str, ...]) -> None:
    """Insert ``child`` respecting the sequence given by ``order`` (a tag list)."""
    if not order:
        parent.append(child)
        return
    try:
        target = order.index(_prefixed(child.tag))
    except ValueError:
        parent.append(child)
        return
    for existing in parent:
        name = _prefixed(existing.tag)
        pos = order.index(name) if name in order else len(order)
        if pos > target:
            existing.addprevious(child)
            return
    parent.append(child)


def _prefixed(tag) -> str:
    if not isinstance(tag, str) or not tag.startswith("{"):
        return str(tag)
    uri, _, local = tag[1:].partition("}")
    for prefix, ns_uri in NS.items():
        if ns_uri == uri:
            return f"{prefix}:{local}"
    return local


#: Child order of ``w:pPr`` (CT_PPr).  Truncated to the members we touch, with
#: ``w:pPrChange`` pinned last as the schema requires.
PPR_ORDER = (
    "w:pStyle",
    "w:keepNext",
    "w:keepLines",
    "w:pageBreakBefore",
    "w:framePr",
    "w:widowControl",
    "w:numPr",
    "w:suppressLineNumbers",
    "w:pBdr",
    "w:shd",
    "w:tabs",
    "w:suppressAutoHyphens",
    "w:kinsoku",
    "w:wordWrap",
    "w:overflowPunct",
    "w:topLinePunct",
    "w:autoSpaceDE",
    "w:autoSpaceDN",
    "w:bidi",
    "w:adjustRightInd",
    "w:snapToGrid",
    "w:spacing",
    "w:ind",
    "w:contextualSpacing",
    "w:mirrorIndents",
    "w:suppressOverlap",
    "w:jc",
    "w:textDirection",
    "w:textAlignment",
    "w:textboxTightWrap",
    "w:outlineLvl",
    "w:divId",
    "w:cnfStyle",
    "w:rPr",
    "w:sectPr",
    "w:pPrChange",
)

#: Child order of the ``w:rPr`` that lives inside ``w:pPr`` (CT_ParaRPr).
PARA_RPR_ORDER = (
    "w:ins",
    "w:del",
    "w:moveFrom",
    "w:moveTo",
    "w:rStyle",
    "w:rFonts",
    "w:b",
    "w:bCs",
    "w:i",
    "w:iCs",
    "w:caps",
    "w:smallCaps",
    "w:strike",
    "w:dstrike",
    "w:outline",
    "w:shadow",
    "w:emboss",
    "w:imprint",
    "w:noProof",
    "w:snapToGrid",
    "w:vanish",
    "w:webHidden",
    "w:color",
    "w:spacing",
    "w:w",
    "w:kern",
    "w:position",
    "w:sz",
    "w:szCs",
    "w:highlight",
    "w:u",
    "w:effect",
    "w:bdr",
    "w:shd",
    "w:fitText",
    "w:vertAlign",
    "w:rtl",
    "w:cs",
    "w:em",
    "w:lang",
    "w:eastAsianLayout",
    "w:specVanish",
    "w:oMath",
    "w:rPrChange",
)

#: Child order of ``w:trPr`` (CT_TrPr) -- ins/del/trPrChange live at the end.
TRPR_ORDER = (
    "w:cnfStyle",
    "w:divId",
    "w:gridBefore",
    "w:gridAfter",
    "w:wBefore",
    "w:wAfter",
    "w:cantSplit",
    "w:trHeight",
    "w:tblHeader",
    "w:tblCellSpacing",
    "w:jc",
    "w:hidden",
    "w:ins",
    "w:del",
    "w:trPrChange",
)


def clone_shell(el: etree._Element) -> etree._Element:
    """An empty element with the same tag, attributes and nsmap as ``el``."""
    clone = oxml_parser.makeelement(el.tag, nsmap=el.nsmap)
    for key, value in el.attrib.items():
        clone.set(key, value)
    return clone


def deepcopy_without(el: etree._Element, tags: tuple[str, ...]) -> etree._Element:
    """Deep copy ``el`` dropping the listed child tags (used for *PrChange baselines)."""
    clone = copy.deepcopy(el)
    for tag in tags:
        for child in clone.findall(qn(tag)):
            clone.remove(child)
    return clone
