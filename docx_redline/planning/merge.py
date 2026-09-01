# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Merging action items proposed by segments that never saw each other.

Each segment is reviewed in isolation, so the pieces arrive with colliding ids,
overlapping edits, and conflicting structural intentions. Applying them as they
come does not fail loudly -- it produces a document that is subtly wrong and a
plan report that says ``applied`` for every item.

So this stage is adversarial towards its own input. It re-ids, drops anything a
segment had no business proposing, resolves contradictions to one winner, and
resolves every target against the untouched document *before* the planner opens
it. Anything it discards is recorded with a reason rather than dropped quietly.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..oxml.ns import qn
from ..oxml.textmap import paragraph_text
from ..structure.clauses import ClauseTree
from ..structure.segments import DocSegment
from .actions import (
    ANNOTATION_ACTIONS,
    SEVERITIES,
    STRUCTURAL_ACTIONS,
    allowed_types,
    validate_actions,
)

__all__ = ["MergeReport", "SegmentResult", "reduce_segments"]

#: Keys that name a clause an action claims. One structural action per label.
TARGET_KEYS = (
    "clause",
    "section",
    "after_clause",
    "before_clause",
    "into_section",
    "after_section",
    "before_section",
)

#: Not part of an action's identity -- two items differing only here are the same edit.
_IDENTITY_EXCLUDED = frozenset({"id", "rationale", "severity", "note"})

#: Structural actions run in this order. Deletes first so a later move into a
#: doomed subtree fails loudly instead of vanishing; inserts last so nothing
#: resolves through a freshly minted, temporarily duplicated clause number.
_STRUCTURAL_ORDER = {
    "delete_section": 0,
    "delete_clause": 1,
    "move_section": 2,
    "move_clause": 3,
    "reorder_clauses": 4,
    "insert_section": 5,
    "insert_clause": 6,
}

_SEVERITY_RANK = {name: index for index, name in enumerate(SEVERITIES)}


@dataclass
class SegmentResult:
    """What one segment's review produced."""

    segment: DocSegment
    items: list[dict]
    status: str = "ok"  # ok | cached | skipped | failed | truncated
    detail: str = ""
    priority: str = "deep"


@dataclass
class MergeReport:
    strategy: str = ""
    segments: list[dict] = field(default_factory=list)
    triage: dict = field(default_factory=dict)
    provenance: dict[str, dict] = field(default_factory=dict)
    dropped: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    kept: int = 0

    def counts_by_severity(self) -> dict[str, int]:
        counts = dict.fromkeys(SEVERITIES, 0)
        for entry in self.provenance.values():
            counts[entry.get("severity", "medium")] = (
                counts.get(entry.get("severity", "medium"), 0) + 1
            )
        return counts

    def to_dict(self) -> dict:
        return {
            "summary": {
                "strategy": self.strategy,
                "segments": len(self.segments),
                "reviewed": sum(1 for s in self.segments if s["status"] in ("ok", "cached")),
                "skipped": sum(1 for s in self.segments if s["status"] == "skipped"),
                "failed": sum(1 for s in self.segments if s["status"] in ("failed", "truncated")),
                "proposed": sum(s["items"] for s in self.segments),
                "kept": self.kept,
                "dropped": len(self.dropped),
                "conflicts": len(self.conflicts),
                "unresolved": len(self.unresolved),
            },
            "segments": self.segments,
            "triage": self.triage,
            "provenance": self.provenance,
            "dropped": self.dropped,
            "conflicts": self.conflicts,
            "unresolved": self.unresolved,
            "usage": self.usage,
        }

    def format(self) -> str:
        s = self.to_dict()["summary"]
        return (
            f"{s['segments']} segments ({s['reviewed']} reviewed, {s['skipped']} skipped, "
            f"{s['failed']} failed): {s['proposed']} proposed -> {s['kept']} kept "
            f"({s['dropped']} duplicate, {s['conflicts']} conflicting, "
            f"{s['unresolved']} unresolvable)"
        )


# ---------------------------------------------------------------------------
def reduce_segments(
    tree: ClauseTree,
    results: Sequence[SegmentResult],
    *,
    max_actions: int | None = None,
) -> tuple[list[dict], MergeReport]:
    """Turn many segment proposals into one plan the planner can run."""
    report = MergeReport()
    for result in results:
        report.segments.append(
            {
                "id": result.segment.id,
                "title": result.segment.title[:70],
                "tokens": result.segment.approx_tokens,
                "priority": result.priority,
                "status": result.status,
                "items": len(result.items),
                "detail": result.detail,
            }
        )

    known = {clause.label for clause in tree}
    staged = _stage(results, report, known)
    staged = _dedupe(staged, report)
    staged = _resolve_conflicts(staged, report)
    staged = _preflight(tree, staged, report)
    staged = _order(staged)
    if max_actions is not None and len(staged) > max_actions:
        staged = _cap(staged, max_actions, report)

    items = []
    for index, entry in enumerate(staged, start=1):
        item = dict(entry["item"])
        item["id"] = f"AI-{index:04d}"
        item["note"] = entry["segment"]
        items.append(item)
        report.provenance[item["id"]] = {
            "segment": entry["segment"],
            "original_id": entry["original_id"],
            "severity": item.get("severity", "medium"),
            "type": item["type"],
        }
    report.kept = len(items)

    # The planner raises on any schema problem and discards the whole run, which
    # is far too expensive here. Anything still malformed goes to the report.
    problems = validate_actions(items)
    if problems:
        bad = {p.split(":", 1)[0].strip() for p in problems}
        keepers = []
        for item in items:
            if item["id"] in bad:
                report.unresolved.append(
                    {"id": item["id"], "reason": "failed validation", "item": item}
                )
                report.provenance.pop(item["id"], None)
            else:
                keepers.append(item)
        items = keepers
        report.kept = len(items)
    return items, report


# ---------------------------------------------------------------------------
def _stage(results: Sequence[SegmentResult], report: MergeReport, known: set[str]) -> list[dict]:
    """Wrap each item with its provenance, dropping what its segment cannot claim."""
    staged: list[dict] = []
    for result in results:
        allowed = allowed_types(result.segment)
        labels = result.segment.labels
        for item in result.items:
            kind = item.get("type")
            if kind not in allowed:
                report.dropped.append(
                    {
                        "segment": result.segment.id,
                        "id": item.get("id"),
                        "reason": f"{kind} needs clause numbering this document does not have",
                        "item": item,
                    }
                )
                continue
            # A segment may only touch what it was shown. Without this the
            # read-only context around a boundary gets edited twice.
            claimed = [str(item[key]) for key in TARGET_KEYS if item.get(key)]
            # Only reject as out-of-scope when the target really is somewhere
            # else; a label that exists nowhere is a hallucination, and saying so
            # is more useful than saying it belongs to another segment.
            elsewhere = [label for label in claimed if label in known]
            if labels and elsewhere and not any(label in labels for label in elsewhere):
                report.dropped.append(
                    {
                        "segment": result.segment.id,
                        "id": item.get("id"),
                        "reason": f"targets {elsewhere} outside this segment",
                        "item": item,
                    }
                )
                continue
            staged.append(
                {"item": item, "segment": result.segment.id, "original_id": item.get("id", "")}
            )
    return staged


def _identity(item: dict) -> tuple:
    """Everything that makes two items the same edit.

    Keying on a handful of fields would collapse unrelated items: ``find`` and
    ``replace`` are both absent on every ``insert_clause``, so a four-field key
    would merge every new clause in the document into one.
    """
    parts = []
    for key in sorted(k for k in item if k not in _IDENTITY_EXCLUDED):
        value = item[key]
        parts.append((key, tuple(value) if isinstance(value, list) else value))
    return tuple(parts)


def _dedupe(staged: list[dict], report: MergeReport) -> list[dict]:
    seen: dict[tuple, dict] = {}
    kept: list[dict] = []
    for entry in staged:
        key = _identity(entry["item"])
        if key in seen:
            report.dropped.append(
                {
                    "segment": entry["segment"],
                    "id": entry["original_id"],
                    "reason": f"identical to {seen[key]['segment']}/{seen[key]['original_id']}",
                    "item": entry["item"],
                }
            )
            continue
        seen[key] = entry
        kept.append(entry)
    return kept


def _severity(entry: dict) -> int:
    return _SEVERITY_RANK.get(entry["item"].get("severity", "medium"), 1)


def _resolve_conflicts(staged: list[dict], report: MergeReport) -> list[dict]:
    """Keep one winner per contested target, most severe first."""
    ranked = sorted(enumerate(staged), key=lambda pair: (-_severity(pair[1]), pair[0]))

    structural_claim: dict[str, dict] = {}
    deleted: set[str] = set()
    rewritten: set[str] = set()
    reordered: set[str] = set()
    insert_anchor: set[tuple] = set()
    spans: dict[str, list[tuple[int, int, dict]]] = {}
    survivors: list[tuple[int, dict]] = []

    def reject(entry, winner, rule) -> None:
        report.conflicts.append(
            {
                "kept": f"{winner['segment']}/{winner['original_id']}" if winner else None,
                "dropped": f"{entry['segment']}/{entry['original_id']}",
                "rule": rule,
                "item": entry["item"],
            }
        )

    for position, entry in ranked:
        item = entry["item"]
        kind = item["type"]
        targets = [str(item[key]) for key in TARGET_KEYS if item.get(key)]
        primary = str(item.get("clause") or item.get("section") or "")

        if any(_inside(target, deleted) for target in targets + ([primary] if primary else [])):
            reject(entry, None, "target is inside a subtree another action deletes")
            continue

        if kind in STRUCTURAL_ACTIONS:
            clash = next((structural_claim[t] for t in targets if t in structural_claim), None)
            if clash is not None:
                reject(entry, clash, "another structural action already claims this clause")
                continue
            if kind == "reorder_clauses":
                if primary in reordered:
                    reject(entry, None, "section already reordered")
                    continue
                reordered.add(primary)
            for target in targets:
                structural_claim[target] = entry
            if kind in ("delete_clause", "delete_section"):
                deleted.add(primary)

        elif kind not in ANNOTATION_ACTIONS:
            if kind == "rewrite_clause":
                if primary in rewritten:
                    reject(entry, None, "clause already rewritten by another segment")
                    continue
                rewritten.add(primary)
            elif primary and primary in rewritten:
                reject(entry, None, "clause is rewritten wholesale by another action")
                continue

            if kind == "insert_text":
                anchor_key = (primary, item.get("anchor"), item.get("position", "after"))
                if anchor_key in insert_anchor:
                    reject(entry, None, "another insertion already uses this anchor")
                    continue
                insert_anchor.add(anchor_key)

            if kind in ("replace_text", "delete_text") and primary and item.get("find"):
                overlap = _overlapping(spans.setdefault(primary, []), item)
                if overlap is not None:
                    reject(entry, overlap, "edits overlap inside the same clause")
                    continue

        survivors.append((position, entry))

    return [entry for _, entry in sorted(survivors, key=lambda pair: pair[0])]


def _inside(label: str, deleted: set[str]) -> bool:
    """Is ``label`` the deleted clause itself, or one of its descendants?"""
    return any(label == gone or label.startswith(f"{gone}.") for gone in deleted)


def _overlapping(existing: list, item: dict) -> dict | None:
    """Record this item's span and return whatever it genuinely overlaps.

    Two edits to one clause are only a conflict when their text actually
    intersects; disjoint edits compose fine and dropping them loses real review.
    Spans are recorded lazily -- the exact offsets come from the pre-flight pass,
    which has the clause text; here we can only compare the quoted strings.
    """
    needle = item.get("find") or ""
    for start, end, owner in existing:
        del start, end
        other = owner.get("find") or ""
        if needle and other and (needle in other or other in needle):
            return {"segment": "", "original_id": owner.get("id", "")}
    existing.append((0, 0, item))
    return None


def _preflight(tree: ClauseTree, staged: list[dict], report: MergeReport) -> list[dict]:
    """Resolve every target against the untouched document before anything runs.

    A hallucinated clause number or a misquoted phrase would otherwise surface
    as a failed action halfway through applying a several-hundred-item plan.
    Here it costs nothing and is explainable.
    """
    labels = {clause.label for clause in tree}
    by_label = {clause.label: clause for clause in tree}
    tables = tree.root.findall(qn("w:tbl"))
    paragraphs = [paragraph_text(p) for p in tree.root.iter(qn("w:p"))]

    kept: list[dict] = []
    for entry in staged:
        item = entry["item"]
        problem = _resolve_problem(item, labels, by_label, tables, paragraphs)
        if problem:
            report.unresolved.append(
                {
                    "segment": entry["segment"],
                    "id": entry["original_id"],
                    "reason": problem,
                    "item": item,
                }
            )
            continue
        kept.append(entry)
    return kept


def _resolve_problem(item, labels, by_label, tables, paragraphs) -> str | None:
    for key in TARGET_KEYS:
        value = item.get(key)
        if value and str(value) not in labels:
            return f"{key}={value!r} is not a clause in this document"

    clause_label = str(item.get("clause") or "")
    for field_name in ("find", "anchor"):
        needle = item.get(field_name)
        if not needle:
            continue
        if item.get("regex"):
            continue
        if clause_label:
            if needle not in by_label[clause_label].text:
                return f"{field_name}={needle!r} does not occur in clause {clause_label}"
        else:
            hits = sum(1 for text in paragraphs if needle in text)
            if hits == 0:
                return f"{field_name}={needle!r} does not occur in the document"
            if hits > 1 and not item.get("all"):
                return f"{field_name}={needle!r} occurs in {hits} paragraphs -- ambiguous"

    if item["type"] == "reorder_clauses":
        children = {c.label for c in by_label[str(item["section"])].children}
        missing = [str(x) for x in item.get("order", []) if str(x) not in children]
        if missing:
            return f"order lists {missing} which are not children of {item['section']}"

    if item.get("table") is not None:
        index = int(item["table"])
        if not 0 <= index < len(tables):
            return f"table={index} is out of range (document has {len(tables)})"
        rows = tables[index].findall(qn("w:tr"))
        row = item.get("row")
        if row is not None and item["type"] != "insert_row" and not 0 <= int(row) < len(rows):
            return f"row={row} is out of range (table {index} has {len(rows)})"
    return None


def _order(staged: list[dict]) -> list[dict]:
    """Content, then structural in dependency order, then annotations."""

    def rank(entry) -> tuple:
        kind = entry["item"]["type"]
        if kind in ANNOTATION_ACTIONS:
            return (2, 0, _document_position(entry))
        if kind in STRUCTURAL_ACTIONS:
            return (1, _STRUCTURAL_ORDER.get(kind, 9), _document_position(entry))
        return (0, 0, _document_position(entry))

    return sorted(staged, key=rank)


def _document_position(entry) -> tuple[int, ...]:
    label = str(entry["item"].get("clause") or entry["item"].get("section") or "")
    if not re.fullmatch(r"\d+(\.\d+)*", label):
        return (9_999,)
    return tuple(int(part) for part in label.split("."))


def _cap(staged: list[dict], limit: int, report: MergeReport) -> list[dict]:
    ranked = sorted(staged, key=lambda e: (-_severity(e), _document_position(e)))
    for entry in ranked[limit:]:
        report.dropped.append(
            {
                "segment": entry["segment"],
                "id": entry["original_id"],
                "reason": f"over the {limit}-action cap",
                "item": entry["item"],
            }
        )
    keep = {id(e) for e in ranked[:limit]}
    return [e for e in staged if id(e) in keep]
