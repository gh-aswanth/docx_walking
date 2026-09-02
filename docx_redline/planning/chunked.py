# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Reviewing a document that will not fit in one useful request.

A 300-page contract is ~280K tokens. That fits a 1M context window, but a single
call has to emit hundreds of action items in one structured output and recall
collapses across that much dense legal text -- findings cluster at the start and
end with a hole in the middle, and every retry re-spends the whole input.

So: cut the document on its own structural boundaries, triage which pieces are
worth a full read, review the survivors concurrently, and merge. The pieces are
segments rather than pages because a ``.docx`` has no pages -- Word computes
pagination at render time -- and because a segment boundary is also a clause
boundary, which keeps every quote whole and every clause number resolvable.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..structure.clauses import ClauseTree
from ..structure.segments import DocSegment, segment_document
from . import agent
from .actions import allowed_types
from .agent import (
    ACTION_OUTPUT,
    SYSTEM_PROMPT,
    OutputSchema,
    Proposal,
    RedlineCredentialsError,
    Reviewer,
    StreamInterrupted,
    TruncatedReply,
    get_reviewer,
    normalize_items,
)
from .merge import MergeReport, SegmentResult, reduce_segments

__all__ = ["ChunkedReviewer", "SegmentCache", "SegmentProgress", "build_index"]

#: Bumped whenever the prompt changes shape, so cached replies invalidate.
PROMPT_VERSION = "1"

#: Keyword families that force a segment to at least a skim, whatever triage says.
RISK_PATTERNS: dict[str, str] = {
    "liability": r"liabilit|limitation of liability|consequential",
    "indemnity": r"indemnif|indemnit|hold harmless",
    "termination": r"terminat|expir",
    "renewal": r"renew|auto-renew",
    "warranty": r"warrant|disclaim",
    "confidentiality": r"confidential|non-disclosure",
    "data": r"personal data|privacy|data protection|breach|GDPR",
    "governing-law": r"governing law|jurisdiction|venue|arbitrat",
    "assignment": r"assign|change of control",
    "audit": r"audit|inspect",
    "insurance": r"insur",
    "ip": r"intellectual property|copyright|patent|trademark",
    "payment": r"fees|payment|invoic|price|charge",
}

TRIAGE_SYSTEM = """\
You are triaging a long agreement before a detailed review. You are given an \
index of its sections -- numbers and titles only, no body text -- and a review \
brief.

For each segment, decide how much attention it needs:
  deep  -- likely to contain something the brief cares about; read in full
  scan  -- read, but only report critical or high-severity issues
  skip  -- boilerplate or irrelevant to this brief

Be conservative: skipping a segment means nobody reads it. When a segment's \
title is uninformative, say scan rather than skip. Where you say deep, list the \
specific things to look for in `focus`.
"""


def _triage_schema(nullable_style: str) -> dict:
    del nullable_style
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["selections", "notes"],
        "properties": {
            "notes": {"type": "string", "description": "One line on the overall shape."},
            "selections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["segment", "priority", "reason", "focus"],
                    "properties": {
                        "segment": {"type": "string", "description": "Segment id, e.g. S07."},
                        "priority": {"type": "string", "enum": ["deep", "scan", "skip"]},
                        "reason": {"type": "string"},
                        "focus": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    }


TRIAGE_OUTPUT = OutputSchema(
    "emit_triage", "Return one selection per segment of the agreement.", _triage_schema
)


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------
@dataclass
class SegmentProgress:
    """Emitted as each piece of work finishes, for a caller that wants a log."""

    phase: str  # segment | triage | map | reduce
    done: int = 0
    total: int = 0
    segment: str | None = None
    status: str = ""  # cached | ok | retry | truncated | failed | skipped
    items: int = 0
    detail: str = ""


# ---------------------------------------------------------------------------
# the compact index
# ---------------------------------------------------------------------------
def risk_families(text: str) -> list[str]:
    """Which risk keyword families this text hits. Local, free, no model."""
    lowered = text.lower()
    return sorted(name for name, pattern in RISK_PATTERNS.items() if re.search(pattern, lowered))


def build_index(segments: Sequence[DocSegment], *, depth: int = 2, max_tokens: int = 12_000) -> str:
    """Titles only, one block per segment -- never body text.

    This is the part of every request that does not change, so it has to be
    small enough to sit in the cached prefix for the whole run. If it does not
    fit, shed depth rather than dropping segments: a segment missing from the
    index is a segment triage cannot select.
    """
    for attempt in range(depth, -1, -1):
        rendered = _render_index(segments, attempt)
        if len(rendered) // 4 <= max_tokens or attempt == 0:
            return rendered
    return _render_index(segments, 0)  # pragma: no cover - loop always returns


def _render_index(segments: Sequence[DocSegment], depth: int) -> str:
    lines: list[str] = []
    for seg in segments:
        risks = risk_families(seg.render())
        head = f"{seg.id}  {seg.title[:70]}  (~{seg.approx_tokens}k tok)".replace(
            f"~{seg.approx_tokens}k", f"~{seg.approx_tokens}"
        )
        if risks:
            head += "  risk: " + ", ".join(risks)
        lines.append(head)
        if depth <= 0:
            continue
        for block in seg.blocks:
            if block.kind != "para" or not block.is_heading or block.level > depth:
                continue
            label = block.clause.label if block.clause else ""
            title = (block.clause.title if block.clause else block.text)[:70]
            lines.append(f"    {label}  {title}".rstrip())
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# per-segment disk cache
# ---------------------------------------------------------------------------
class SegmentCache:
    """Remembers each segment's reply so an interrupted run resumes for free.

    A twenty-call review that dies on call twelve should not re-spend the first
    eleven. The key covers everything that would change the answer, so editing
    the brief or the prompt invalidates by construction rather than by hand.
    """

    #: Set when the directory could not be created, so callers can say why the
    #: cache is off instead of silently getting no reuse.
    error: OSError | None = None

    def __init__(
        self, directory: str | Path, *, enabled: bool = True, refresh: bool = False
    ) -> None:
        self.directory = Path(directory)
        self.enabled = enabled
        self.refresh = refresh
        if self.enabled:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                # The default location is under the user's home, which is
                # read-only on a serverless host and may be absent in a
                # container. A cache that cannot be created is a lost
                # optimisation, not a failed review -- carry on without it.
                self.enabled = False
                self.error = exc

    @staticmethod
    def key(*parts: str) -> str:
        digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
        return digest[:32]

    def get(self, key: str) -> dict | None:
        if not self.enabled or self.refresh:
            return None
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # pragma: no cover - corrupt entry
            return None

    def put(self, key: str, payload: dict) -> None:
        if not self.enabled:
            return
        (self.directory / f"{key}.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# the reviewer
# ---------------------------------------------------------------------------
class ChunkedReviewer:
    """Segments a document, reviews the pieces concurrently, merges the results.

    Satisfies the plain ``Reviewer`` protocol, so it drops into the pipeline
    wherever a single-call reviewer goes.
    """

    def __init__(
        self,
        engine: Reviewer | str = "claude",
        *,
        segment_tokens: int = 25_000,
        index_tokens: int = 12_000,
        concurrency: int = 6,
        triage: bool = True,
        triage_effort: str = "low",
        min_coverage: float = 0.35,
        max_actions: int | None = None,
        cache_dir: str | Path | None = None,
        use_cache: bool = True,
        refresh: bool = False,
        strategy: str = "auto",
        max_attempts: int = 3,
        max_split_depth: int = 2,
        backoff: float = 1.0,
        on_progress: Callable[[SegmentProgress], None] | None = None,
        **engine_options: Any,
    ) -> None:
        self.engine = get_reviewer(engine, **engine_options) if isinstance(engine, str) else engine
        self.segment_tokens = segment_tokens
        self.index_tokens = index_tokens
        self.concurrency = max(1, concurrency)
        self.triage_enabled = triage
        self.triage_effort = triage_effort
        self.min_coverage = min_coverage
        self.max_actions = max_actions
        self.strategy = strategy
        self.max_attempts = max(1, max_attempts)
        self.max_split_depth = max(0, max_split_depth)
        self.backoff = backoff
        self.on_progress = on_progress
        self.cache = SegmentCache(
            cache_dir or Path.home() / ".cache" / "docx-redline",
            enabled=use_cache,
            refresh=refresh,
        )
        self.report: MergeReport | None = None

    # -- plumbing -------------------------------------------------------
    def _emit(self, progress: SegmentProgress) -> None:
        if self.on_progress:
            self.on_progress(progress)

    @property
    def model(self) -> str | None:
        return getattr(self.engine, "model", None)

    # -- entry point ----------------------------------------------------
    def propose(self, tree: ClauseTree, brief: str) -> Proposal:
        started = time.monotonic()
        segments = segment_document(
            tree.root, budget_tokens=self.segment_tokens, strategy=self.strategy, tree=tree
        )
        if not segments:
            return Proposal(action_items=[], summary="", source="chunked:empty")
        self._emit(
            SegmentProgress(
                "segment", len(segments), len(segments), detail=f"{segments[0].strategy} strategy"
            )
        )

        index = build_index(segments, max_tokens=self.index_tokens)
        usage: dict[str, Any] = {}
        priorities, triage_notes = self._triage(segments, index, brief, usage)

        results = self._map(segments, index, brief, priorities, usage)
        attempted = [r for r in results if r.status != "skipped"]
        if attempted and all(r.status in ("failed", "truncated") for r in attempted):
            detail = next((r.detail for r in attempted if r.detail), "no detail")
            raise RuntimeError(
                f"every one of the {len(attempted)} reviewed segments failed ({detail}); "
                "returning an empty result would look like a clean bill of health"
            )

        items, report = reduce_segments(tree, results, max_actions=self.max_actions)
        report.strategy = segments[0].strategy
        report.triage = {"notes": triage_notes, "priorities": priorities}
        usage["calls"] = usage.get("calls", 0)
        usage["wall_seconds"] = round(time.monotonic() - started, 1)
        report.usage = usage
        self.report = report
        self._emit(SegmentProgress("reduce", len(results), len(results), items=len(items)))

        return Proposal(
            action_items=items,
            summary=self._summarise(report, triage_notes),
            source=f"chunked:{getattr(self.engine, 'source_name', self._engine_name())}",
            model=self.model,
            usage=usage,
            merge=report.to_dict(),
        )

    def _engine_name(self) -> str:
        return type(self.engine).__name__.replace("Reviewer", "").lower()

    # -- triage ---------------------------------------------------------
    def _triage(
        self, segments: Sequence[DocSegment], index: str, brief: str, usage: dict
    ) -> tuple[dict[str, str], str]:
        """Decide how much attention each segment gets, with floors.

        The model's answer is advice, not authority: silence means ``scan``, a
        keyword-heavy segment cannot be skipped, and if too little of the
        document is selected for a full read the selection is widened until it
        is. Skipping is the one decision here that loses information silently.
        """
        priorities = {seg.id: "deep" for seg in segments}
        if not self.triage_enabled or len(segments) == 1:
            return priorities, "triage disabled"

        try:
            reply = self.engine.emit(
                system=TRIAGE_SYSTEM,
                cached=f"<document_index>\n{index}\n</document_index>",
                variable=f"<review_brief>\n{brief}\n</review_brief>",
                output=TRIAGE_OUTPUT,
                effort=self.triage_effort,
                cache_key=f"docx-redline-triage:{self.cache.key(index, PROMPT_VERSION)}",
            )
        except RedlineCredentialsError:
            raise  # not a transient failure -- degrading to "no findings" hides it
        except (TruncatedReply, RuntimeError) as exc:
            self._emit(SegmentProgress("triage", status="failed", detail=str(exc)[:80]))
            return priorities, f"triage failed, reviewing everything: {exc}"

        _accumulate(usage, reply.usage)
        usage["calls"] = usage.get("calls", 0) + 1

        known = {seg.id for seg in segments}
        chosen: dict[str, str] = {}
        for entry in reply.payload.get("selections", []):
            segment_id = str(entry.get("segment", ""))
            if segment_id in known and entry.get("priority") in ("deep", "scan", "skip"):
                chosen[segment_id] = entry["priority"]

        by_id = {seg.id: seg for seg in segments}
        for seg in segments:
            # Never let silence mean exclusion.
            priorities[seg.id] = chosen.get(seg.id, "scan")
            if priorities[seg.id] == "skip" and len(risk_families(seg.render())) >= 2:
                priorities[seg.id] = "scan"

        self._enforce_coverage(segments, priorities, by_id)
        self._emit(
            SegmentProgress(
                "triage",
                len(segments),
                len(segments),
                status="ok",
                detail=", ".join(
                    f"{p}:{sum(1 for v in priorities.values() if v == p)}"
                    for p in ("deep", "scan", "skip")
                ),
            )
        )
        return priorities, reply.payload.get("notes", "")

    def _enforce_coverage(self, segments, priorities: dict[str, str], by_id) -> None:
        total = sum(seg.approx_tokens for seg in segments) or 1
        covered = sum(by_id[i].approx_tokens for i, p in priorities.items() if p == "deep")
        if covered / total >= self.min_coverage:
            return
        candidates = sorted(
            (i for i, p in priorities.items() if p != "deep"),
            key=lambda i: (-len(risk_families(by_id[i].render())), -by_id[i].approx_tokens),
        )
        for segment_id in candidates:
            priorities[segment_id] = "deep"
            covered += by_id[segment_id].approx_tokens
            if covered / total >= self.min_coverage:
                return

    # -- map ------------------------------------------------------------
    def _map(self, segments, index, brief, priorities, usage) -> list[SegmentResult]:
        selected = [s for s in segments if priorities.get(s.id) != "skip"]
        results: list[SegmentResult] = [
            SegmentResult(
                segment=s, items=[], status="skipped", detail="triage: skip", priority="skip"
            )
            for s in segments
            if priorities.get(s.id) == "skip"
        ]
        if not selected:
            return results

        done = 0
        self._emit(
            SegmentProgress(
                "map",
                0,
                len(selected),
                detail=(f"{len(selected)} segment(s) to review, {self.concurrency} at a time"),
            )
        )
        # Prime one call before fanning out: the first request writes the shared
        # cache prefix that the rest read, and it constructs the SDK client on
        # this thread rather than racing to do it on several at once.
        first = self._review_segment(selected[0], index, brief, priorities, usage)
        results.append(first)
        done += 1
        self._emit(
            SegmentProgress(
                "map",
                done,
                len(selected),
                first.segment.id,
                first.status,
                len(first.items),
                first.detail,
            )
        )

        if len(selected) > 1:
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                futures = [
                    pool.submit(self._review_segment, seg, index, brief, priorities, usage)
                    for seg in selected[1:]
                ]
                for future in futures:
                    result = future.result()
                    results.append(result)
                    done += 1
                    self._emit(
                        SegmentProgress(
                            "map",
                            done,
                            len(selected),
                            result.segment.id,
                            result.status,
                            len(result.items),
                            result.detail,
                        )
                    )
        results.sort(key=lambda r: r.segment.index)
        return results

    def _review_segment(
        self, seg, index, brief, priorities, usage, depth: int = 0
    ) -> SegmentResult:
        priority = priorities.get(seg.id, "deep")
        cached, variable = self._prompt_for(seg, index, brief, priority)
        key = self.cache.key(
            self._engine_name(), str(self.model), priority, PROMPT_VERSION, brief, seg.render()
        )
        hit = self.cache.get(key)
        if hit is not None:
            return SegmentResult(
                seg, hit.get("action_items", []), "cached", priority=priority, detail="from cache"
            )

        attempts = 0
        budget = None
        while attempts < self.max_attempts:
            attempts += 1
            # Say what is happening before blocking on it. A reasoning-heavy
            # call runs for minutes, and silence for that long is
            # indistinguishable from a hang.
            self._emit(
                SegmentProgress(
                    "map",
                    segment=seg.id,
                    status="sending",
                    detail=f"{seg.approx_tokens} tok, {priority}"
                    + (f", attempt {attempts}" if attempts > 1 else ""),
                )
            )
            ticker = _Heartbeat(self._emit, seg.id)
            try:
                reply = self.engine.emit(
                    system=SYSTEM_PROMPT,
                    cached=cached,
                    variable=variable,
                    output=ACTION_OUTPUT,
                    effort="low" if priority == "scan" else None,
                    max_tokens=budget,
                    cache_key=f"docx-redline:{self.cache.key(index, brief, PROMPT_VERSION)}",
                    on_event=ticker,
                )
            except StreamInterrupted as exc:
                # Bytes were flowing and then stopped. Repeating the same
                # request reproduces it, so go straight to a smaller span
                # instead of spending three more full-length attempts.
                self._emit(
                    SegmentProgress(
                        "map",
                        segment=seg.id,
                        status="interrupted",
                        detail="stream ended early, splitting",
                    )
                )
                return self._split_and_retry(seg, index, brief, priorities, usage, exc, depth)
            except TruncatedReply as exc:
                # Give it more room once; if that is still not enough the span
                # is genuinely too big, so halve it rather than keep paying.
                if budget is None:
                    budget = min(32_000, getattr(self.engine, "max_tokens", 16_000) * 2)
                    self._emit(
                        SegmentProgress(
                            "map",
                            segment=seg.id,
                            status="truncated",
                            detail="retrying with a larger ceiling",
                        )
                    )
                    continue
                return self._split_and_retry(seg, index, brief, priorities, usage, exc, depth)
            except RedlineCredentialsError:
                raise
            except RuntimeError as exc:
                if attempts >= self.max_attempts:
                    return SegmentResult(
                        seg, [], "failed", priority=priority, detail=str(exc)[:160]
                    )
                self._emit(
                    SegmentProgress("map", segment=seg.id, status="retry", detail=str(exc)[:80])
                )
                time.sleep(min(2**attempts, 8) * self.backoff)
                continue
            _accumulate(usage, reply.usage)
            usage["calls"] = usage.get("calls", 0) + 1
            items = normalize_items(reply.payload.get("action_items", []))
            self.cache.put(
                key, {"action_items": items, "summary": reply.payload.get("summary", "")}
            )
            return SegmentResult(seg, items, "ok", priority=priority)
        return SegmentResult(seg, [], "failed", priority=priority, detail="exhausted retries")

    def _split_and_retry(self, seg, index, brief, priorities, usage, exc, depth=0) -> SegmentResult:
        halves = seg.split() if depth < self.max_split_depth else None
        if halves is None:
            return SegmentResult(
                seg, [], "truncated", priority=priorities.get(seg.id, "deep"), detail=str(exc)[:160]
            )
        merged: list[dict] = []
        parts = []
        for half in halves:
            part = self._review_segment(half, index, brief, priorities, usage, depth + 1)
            merged.extend(part.items)
            parts.append(part)
        # Don't launder the halves' outcome: if neither could be reviewed, the
        # parent has not been reviewed either, however tidy the return looks.
        succeeded = [p for p in parts if p.status in ("ok", "cached")]
        if not succeeded:
            return SegmentResult(
                seg,
                merged,
                "truncated",
                priority=priorities.get(seg.id, "deep"),
                detail=f"split into {len(parts)}, none could be reviewed",
            )
        detail = "split after truncation"
        if len(succeeded) < len(parts):
            detail += f" ({len(parts) - len(succeeded)} of {len(parts)} halves failed)"
        return SegmentResult(
            seg, merged, "ok", priority=priorities.get(seg.id, "deep"), detail=detail
        )

    def _prompt_for(self, seg, index, brief, priority) -> tuple[str, str]:
        """Everything invariant first, the segment last.

        The brief is constant across every segment in a run, so it belongs in
        the cached prefix with the index -- the opposite of where a single-shot
        review puts it, where the contract is the constant part.
        """
        cached = (
            f"<review_brief>\n{brief}\n</review_brief>\n\n"
            f"<document_index>\n{index}\n</document_index>"
        )
        instruction = (
            "Review only the segment below. The index is context: do not propose "
            "edits to anything outside this segment."
        )
        if priority == "scan":
            instruction += " Report only critical and high-severity issues."
        if "move_clause" not in allowed_types(seg):
            instruction += (
                " This document has no clause numbering, so do not emit structural "
                "actions; target text with a unique `find` quote instead."
            )
        variable = (
            f"<instruction>\n{instruction}\n</instruction>\n\n"
            f'<segment id="{seg.id}" title="{seg.title[:70]}">\n{seg.render()}\n</segment>'
        )
        return cached, variable

    # -- reporting ------------------------------------------------------
    @staticmethod
    def _summarise(report: MergeReport, notes: str) -> str:
        counts = report.counts_by_severity()
        ordered = ", ".join(f"{n} {sev}" for sev, n in counts.items() if n)
        reviewed = sum(1 for s in report.segments if s["status"] in ("ok", "cached"))
        parts = [
            f"Reviewed {reviewed} of {len(report.segments)} segments; "
            f"{report.kept} action items ({ordered or 'none'})."
        ]
        if notes:
            parts.append(notes)
        return " ".join(parts)


# Registered here rather than in agent.py: this module imports that one, so the
# dependency only runs in this direction.
_REGISTER = {"chunked": ChunkedReviewer, "map-reduce": ChunkedReviewer, "long": ChunkedReviewer}
agent.REVIEWERS.update(_REGISTER)


class _Heartbeat:
    """Reports that a call is alive, without flooding the log.

    A reasoning model sends nothing for a long time and then thousands of
    events. Neither silence nor a wall of output tells you much, so report the
    first sign of life and then at most once every few seconds.
    """

    def __init__(self, emit, segment_id: str, every: float = 5.0) -> None:
        self._emit = emit
        self._segment = segment_id
        self._every = every
        self._events = 0
        self._started = time.monotonic()
        self._last = 0.0

    def __call__(self, event_type: str) -> None:
        self._events += 1
        now = time.monotonic() - self._started
        if self._events == 1 or now - self._last >= self._every:
            self._last = now
            self._emit(
                SegmentProgress(
                    "map",
                    segment=self._segment,
                    status="streaming",
                    detail=f"{now:.0f}s, {self._events} events",
                )
            )


def _accumulate(total: dict[str, Any], usage: dict[str, Any]) -> None:
    """Sum token counts by key -- the two providers name their cache fields differently."""
    for key, value in (usage or {}).items():
        if isinstance(value, (int, float)):
            total[key] = total.get(key, 0) + value
