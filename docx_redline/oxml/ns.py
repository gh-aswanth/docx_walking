# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""OOXML namespace helpers.

We deliberately keep our own tiny ``qn`` instead of relying on python-docx's
prefix registry so that this package works even if python-docx changes its
internal ``nsmap``.
"""

from __future__ import annotations

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML = "http://www.w3.org/XML/1998/namespace"

NS = {"w": W, "w14": W14, "r": R, "xml": XML}


def qn(tag: str) -> str:
    """``qn("w:ins")`` -> ``"{http://...main}ins"``."""
    prefix, _, local = tag.partition(":")
    if not local:
        return prefix
    try:
        uri = NS[prefix]
    except KeyError as exc:  # pragma: no cover - programmer error
        raise ValueError(f"unknown namespace prefix {prefix!r}") from exc
    return f"{{{uri}}}{local}"


def nstag(el) -> str:
    """Return ``prefix:local`` for an lxml element, for readable messages."""
    tag = el.tag
    if not isinstance(tag, str) or not tag.startswith("{"):
        return str(tag)
    uri, _, local = tag[1:].partition("}")
    for prefix, ns_uri in NS.items():
        if ns_uri == uri:
            return f"{prefix}:{local}"
    return local
