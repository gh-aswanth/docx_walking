# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Word-level diffing used to turn "here is the new sentence" into minimal markup.

Rewriting a whole paragraph as one delete + one insert is valid but unreadable;
reviewers want to see only the words that actually moved.  We tokenise on word
boundaries so that punctuation and whitespace ride along with their word.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

_TOKEN = re.compile(r"\w+|\s+|[^\w\s]", re.UNICODE)


@dataclass(frozen=True)
class TextOp:
    """A single edit expressed in character offsets of the *original* text."""

    kind: str  # "insert" | "delete" | "replace"
    start: int
    end: int
    text: str = ""

    @property
    def is_noop(self) -> bool:
        return self.kind == "replace" and self.start == self.end and not self.text


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text)


def _spans(tokens: list[str]) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for token in tokens:
        spans.append((pos, pos + len(token)))
        pos += len(token)
    return spans


def _key(tokens: list[str], ignore_case: bool) -> list[str]:
    return [t.lower() for t in tokens] if ignore_case else tokens


def diff_ops(
    original: str,
    revised: str,
    ignore_case: bool = False,
    ignore_whitespace: bool = True,
) -> list[TextOp]:
    """Minimal word-level edit script turning ``original`` into ``revised``.

    ``ignore_whitespace`` folds pure-whitespace runs into the neighbouring edit
    instead of reporting them as standalone changes, which keeps Word's markup
    from filling up with one-space insertions.
    """
    if original == revised:
        return []

    a_tokens, b_tokens = tokenize(original), tokenize(revised)
    a_spans = _spans(a_tokens)
    matcher = SequenceMatcher(
        None, _key(a_tokens, ignore_case), _key(b_tokens, ignore_case), autojunk=False
    )

    raw: list[TextOp] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        start = a_spans[i1][0] if i1 < len(a_spans) else len(original)
        end = a_spans[i2 - 1][1] if i2 > i1 else start
        new_text = "".join(b_tokens[j1:j2])
        if tag == "insert":
            raw.append(TextOp("insert", start, start, new_text))
        elif tag == "delete":
            raw.append(TextOp("delete", start, end))
        else:
            raw.append(TextOp("replace", start, end, new_text))

    if ignore_whitespace:
        raw = [op for op in raw if original[op.start : op.end].strip() or op.text.strip()]
    return _merge_adjacent(raw, original)


def _merge_adjacent(ops: list[TextOp], original: str, gap: int = 3) -> list[TextOp]:
    """Coalesce edits separated by only a couple of unchanged characters.

    Two strikeouts split by a single space read as noise; merged, they read as
    one revision.
    """
    if not ops:
        return ops
    merged = [ops[0]]
    for op in ops[1:]:
        prev = merged[-1]
        between = original[prev.end : op.start]
        if op.start - prev.end <= gap and between.strip() == "":
            merged[-1] = TextOp(
                "replace",
                prev.start,
                op.end,
                _op_text(prev, original) + between + _op_text(op, original),
            )
        else:
            merged.append(op)
    return [op for op in merged if not op.is_noop]


def _op_text(op: TextOp, original: str) -> str:
    return op.text if op.kind != "delete" else ""
