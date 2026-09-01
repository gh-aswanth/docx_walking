# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Where action items come from.

Three reviewers, one interface (:class:`Reviewer`):

* :class:`ClaudeReviewer` -- Anthropic. Sends the contract outline to Claude and
  gets action items back through a *forced tool call*.
* :class:`OpenAIReviewer` -- OpenAI. Same job through the Responses API's
  *structured outputs*, which constrains the reply to the same JSON Schema.
* :class:`RuleBasedReviewer` -- no model at all. Produces the same shape
  deterministically from local rules. It is the default because it needs no API
  key and makes the pipeline reproducible in tests and CI.

Both model-backed reviewers are built from one field table
(:data:`ACTION_FIELDS`), so the two providers can never drift apart on what an
action item may contain. Each provider only differs in how it is *told* to obey
the schema; the result is the same list of plain dicts, which
:func:`docx_redline.planning.actions.validate_actions` checks before anything touches
the document.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..structure.clauses import ClauseTree
from ..structure.segments import render_document
from .actions import ACTION_SCHEMA, SEVERITIES, validate_actions

#: Anthropic default. Override with ``ClaudeReviewer(model=...)``.
DEFAULT_CLAUDE_MODEL = "claude-opus-5"
#: OpenAI default. The installed SDK's ``openai.types.shared.chat_model.ChatModel``
#: literal is the authoritative list of what the account may call.
DEFAULT_OPENAI_MODEL = "gpt-5.5"
#: Back-compat alias.
DEFAULT_MODEL = DEFAULT_CLAUDE_MODEL

SYSTEM_PROMPT = """\
You are a contract review assistant. You are given the full text of an agreement \
and a review brief. Return a list of concrete edit actions that a redlining \
engine will apply to the .docx as Word tracked changes.

You are shown the whole document, not just the numbered clauses: the recitals, \
the signature blocks, every table, and the exhibits and schedules at the end. \
Review all of it. Commercial terms often live in an exhibit rather than in a \
numbered clause.

Targeting:
- For numbered clauses, set `clause` to the number shown (e.g. "3.2", "12.1").
- For anything unnumbered -- recitals, exhibits, signature blocks -- omit \
`clause` and quote the text in `find`. That quote must be unique in the whole \
document, so include enough surrounding words to make it so; an ambiguous quote \
is rejected rather than applied to the wrong paragraph.
- Tables are shown as `[table N]` with numbered rows. Edit them with \
`update_cell` / `insert_row` / `delete_row` using those indices.
- `find` must be quoted exactly as it appears, including punctuation.

Rules:
- One action per discrete change. Give every action a stable id and a one-line \
rationale a lawyer would accept.
- NEVER renumber clauses yourself and never mention consequential numbering in \
an action. When you move, insert or delete a clause, the engine recomputes \
every clause number and rewrites every cross-reference itself. Emitting your \
own renumbering would double-apply it.
- Prefer `rewrite_clause` over several overlapping `replace_text` actions on \
the same clause.
"""


class RedlineCredentialsError(RuntimeError):
    """Raised when a model-backed reviewer has no usable credentials."""


#: Substrings that mark an SDK exception as "you have no key", in either vendor's
#: wording, whether it surfaces from the constructor or from the first request.
_AUTH_MARKERS = ("api_key", "api key", "credential", "authentication", "auth_token")


@contextmanager
def _credential_errors(package: str, env_var: str, how: str):
    """Translate either SDK's credential failure into one actionable line.

    The two SDKs fail at different moments -- OpenAI refuses to construct a
    client without a key, Anthropic constructs happily and rejects the first
    request -- so this wraps both the constructor and the call.
    """
    try:
        yield
    except RedlineCredentialsError:
        raise
    except Exception as exc:
        text = str(exc).lower()
        if any(marker in text for marker in _AUTH_MARKERS):
            raise RedlineCredentialsError(
                f"no {package} credentials found -- set {env_var}, {how}, "
                f"or pass api_key=... to the reviewer"
            ) from exc
        raise


class Reviewer(Protocol):
    """Anything that can turn a contract into action items."""

    def propose(self, tree: ClauseTree, brief: str) -> Proposal: ...


@dataclass
class Proposal:
    """The reviewer's output, before anything is applied."""

    action_items: list[dict]
    summary: str = ""
    source: str = "unknown"
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    #: Set by a chunked run: how the segments were reviewed and reconciled.
    merge: dict | None = None

    def to_dict(self, document: str | None = None, author: str | None = None) -> dict:
        payload: dict[str, Any] = {
            "generated_by": self.source,
            "summary": self.summary,
            "action_items": self.action_items,
        }
        if document:
            payload = {"document": document, **payload}
        if author:
            payload["author"] = author
        if self.model:
            payload["model"] = self.model
        if self.usage:
            payload["usage"] = self.usage
        if self.merge:
            payload["merge"] = self.merge
        return payload


# ---------------------------------------------------------------------------
# the schema both providers are held to
# ---------------------------------------------------------------------------
#: One field table, two providers.  Optional fields are declared nullable
#: because both vendors' strict modes require *every* property to be listed in
#: ``required``; the nulls are stripped again by :func:`normalize_items`.
ACTION_FIELDS: dict[str, dict] = {
    "id": {"type": "string", "description": "Stable identifier, e.g. AI-001."},
    "type": {"type": "string", "enum": sorted(ACTION_SCHEMA), "description": "Action kind."},
    "rationale": {"type": "string", "description": "One line justifying the change."},
    "severity": {"type": "string", "enum": list(SEVERITIES)},
    "clause": {
        "type": ["string", "null"],
        "description": "Clause number the action targets, e.g. '3.2'.",
    },
    "find": {"type": ["string", "null"], "description": "Exact text to match."},
    "replace": {"type": ["string", "null"], "description": "Replacement text."},
    "text": {"type": ["string", "null"], "description": "New or rewritten text."},
    "anchor": {"type": ["string", "null"], "description": "Existing phrase to insert relative to."},
    "position": {"type": "string", "enum": ["before", "after", "start", "end", "first", "last"]},
    "title": {"type": ["string", "null"], "description": "Heading for a new clause or section."},
    "after_clause": {"type": ["string", "null"]},
    "before_clause": {"type": ["string", "null"]},
    "into_section": {"type": ["string", "null"]},
    "section": {"type": ["string", "null"]},
    "after_section": {"type": ["string", "null"]},
    "before_section": {"type": ["string", "null"]},
    "order": {
        "type": ["array", "null"],
        "items": {"type": "string"},
        "description": "reorder_clauses only: the section's current clause numbers "
        "in the desired new order.",
    },
    "all": {"type": ["boolean", "null"], "description": "Apply to every occurrence."},
    "regex": {"type": ["boolean", "null"]},
    "table": {"type": ["integer", "null"], "description": "Zero-based table index."},
    "row": {"type": ["integer", "null"]},
    "col": {"type": ["integer", "null"]},
    "values": {"type": ["array", "null"], "items": {"type": "string"}},
    "bold": {"type": ["boolean", "null"]},
    "italic": {"type": ["boolean", "null"]},
    "underline": {"type": ["boolean", "null"]},
    "color": {"type": ["string", "null"], "description": "Hex RGB, e.g. C00000."},
    "highlight": {"type": ["string", "null"]},
    "alignment": {"type": "string", "enum": ["LEFT", "CENTER", "RIGHT", "JUSTIFY"]},
    "space_after": {"type": ["number", "null"], "description": "Points."},
    "space_before": {"type": ["number", "null"], "description": "Points."},
    "style": {"type": ["string", "null"]},
}

#: Fields every action item must actually carry a value for.  Everything else
#: in the table is widened to accept ``null``.
MANDATORY_FIELDS = ("id", "type", "rationale", "severity")

SCHEMA_NAME = "emit_action_items"
SCHEMA_DESCRIPTION = (
    "Return the ordered list of edits to apply to the agreement. "
    "Structural actions (move/reorder/insert/delete of a clause or section) "
    "trigger automatic renumbering and cross-reference updates downstream -- "
    "do not emit renumbering actions yourself."
)


def _nullable(field: dict, style: str) -> dict:
    """Make one field accept ``null``, in whichever dialect the vendor wants.

    ``"inline"`` widens the ``type`` in place. That is fine until the field also
    carries an ``enum``, where a null member would have to be smuggled into the
    value list; ``"anyof"`` keeps the enum clean by putting the null branch
    beside it instead.
    """
    if "null" in field.get("type", ""):
        return dict(field)
    if "enum" not in field:
        widened = dict(field)
        widened["type"] = [field["type"], "null"]
        return widened
    if style == "anyof":
        branch = {k: v for k, v in field.items() if k != "description"}
        widened = {"anyOf": [branch, {"type": "null"}]}
        if "description" in field:
            widened["description"] = field["description"]
        return widened
    widened = dict(field)
    widened["type"] = [field["type"], "null"]
    widened["enum"] = [*list(field["enum"]), None]
    return widened


def action_schema(nullable_style: str = "inline") -> dict:
    """The JSON Schema for a whole reviewer response.

    Both vendors' strict modes demand that every property appear in
    ``required`` and that ``additionalProperties`` be false, so optionality is
    expressed by allowing ``null`` -- see :func:`normalize_items`, which strips
    those nulls straight back out before validation.
    """
    fields = {
        name: dict(spec) if name in MANDATORY_FIELDS else _nullable(spec, nullable_style)
        for name, spec in ACTION_FIELDS.items()
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "action_items"],
        "properties": {
            "summary": {
                "type": "string",
                "description": "Two sentences on the overall position taken.",
            },
            "action_items": {
                "type": "array",
                "description": "Edits in the order they should be applied.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(fields),
                    "properties": fields,
                },
            },
        },
    }


#: Anthropic tool definition -- the model is forced to call this.
@dataclass(frozen=True)
class OutputSchema:
    """One JSON Schema, rendered into whichever dialect a provider wants."""

    name: str
    description: str
    build: Callable[[str], dict]

    def tool(self) -> dict:
        """Anthropic forced-tool block."""
        return {
            "name": self.name,
            "description": self.description,
            "strict": True,
            "input_schema": self.build("inline"),
        }

    def text_format(self) -> dict:
        """OpenAI Responses ``text.format`` block."""
        return {
            "format": {
                "type": "json_schema",
                "name": self.name,
                "description": self.description,
                "strict": True,
                "schema": self.build("anyof"),
            }
        }


ACTION_OUTPUT = OutputSchema(SCHEMA_NAME, SCHEMA_DESCRIPTION, action_schema)

#: Kept as module constants because the tests and older callers import them.
ACTION_TOOL = ACTION_OUTPUT.tool()


class StreamInterrupted(RuntimeError):
    """The response stream ended before the model finished.

    Distinct from a timeout: bytes were flowing and then stopped without a
    completion event. Retrying the same request unchanged tends to reproduce it,
    so the useful responses are a smaller span or less reasoning -- which is why
    the caller treats this like a truncation rather than a transient error.
    """


class TruncatedReply(RuntimeError):
    """The model ran out of output room mid-answer.

    Worth its own type because the caller can do something about it -- raise the
    ceiling, or split the request -- whereas every other failure needs a human.
    """


@dataclass
class Reply:
    """One provider round trip, normalised."""

    payload: dict
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    stop_reason: str = ""


def openai_text_format() -> dict:
    """OpenAI Responses API ``text.format`` block for the action schema."""
    return ACTION_OUTPUT.text_format()


def normalize_items(items: Sequence[dict]) -> list[dict]:
    """Drop the nulls strict-mode schemas force the model to emit."""
    cleaned = []
    for index, item in enumerate(items):
        trimmed = {k: v for k, v in item.items() if v is not None and v != ""}
        trimmed.setdefault("id", f"AI-{index + 1:04d}")
        cleaned.append(trimmed)
    return cleaned


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------
class ClaudeReviewer:
    """Generates action items with Claude, constrained by a forced tool call.

    Server-side refusal fallbacks are enabled: if a safety classifier declines
    the request, the API re-runs it on a fallback model inside the same call
    rather than returning nothing. Pass ``fallbacks=False`` to turn that off.
    """

    def __init__(
        self,
        model: str = DEFAULT_CLAUDE_MODEL,
        effort: str = "high",
        max_tokens: int = 16000,
        api_key: str | None = None,
        fallbacks: bool = True,
        client: Any = None,
        stream: bool = True,
        timeout: float | None = 300.0,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.fallbacks = fallbacks
        self._client = client
        self._api_key = api_key
        #: Stream by default. A reasoning-heavy review can run for minutes, and a
        #: non-streaming request that long risks hitting an HTTP read timeout
        #: with nothing to show for the wait.
        self.stream = stream
        self.timeout = timeout

    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "the Claude reviewer needs the anthropic SDK: pip install anthropic"
                ) from exc
            options = {"api_key": self._api_key} if self._api_key else {}
            with self._credentials():
                self._client = anthropic.Anthropic(**options)
        return self._client

    @staticmethod
    def _credentials():
        return _credential_errors("Anthropic", "ANTHROPIC_API_KEY", "run `ant auth login`")

    def emit(
        self,
        *,
        system: str,
        cached: str,
        variable: str,
        output: OutputSchema,
        max_tokens: int | None = None,
        effort: str | None = None,
        cache_key: str | None = None,
        on_event: Callable[[str], None] | None = None,
    ) -> Reply:
        """One forced-tool round trip.

        ``cached`` is everything invariant across a run and sits behind the cache
        breakpoint; ``variable`` is the only part that changes per request. For a
        single-shot review that split is contract / brief; for a chunked run it
        is index+brief / segment. ``cache_key`` is ignored here -- Anthropic
        caches by prefix bytes, so the split itself is the key.
        """
        del cache_key
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": effort or self.effort},
            "tools": [output.tool()],
            "tool_choice": {"type": "tool", "name": output.name},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": cached, "cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": variable},
                    ],
                }
            ],
        }
        if self.timeout is not None:
            request["timeout"] = self.timeout
        with self._credentials():
            if self.fallbacks:
                request["betas"] = ["server-side-fallback-2026-07-01"]
                request["fallbacks"] = "default"
                messages = self.client.beta.messages
            else:
                messages = self.client.messages
            if self.stream:
                with messages.stream(**request) as live:
                    # Drain the events ourselves rather than calling
                    # get_final_message() straight away: a reasoning-heavy call
                    # sends nothing for minutes, and a caller that cannot see
                    # the stream ticking cannot tell it apart from a hang.
                    for event in live:
                        if on_event:
                            on_event(getattr(event, "type", "event"))
                    try:
                        response = live.get_final_message()
                    except RuntimeError as exc:
                        if "completed" in str(exc).lower() or "final" in str(exc).lower():
                            raise StreamInterrupted(
                                f"the response stream ended before the model finished ({exc}). "
                                "Lower --effort, reduce --segment-tokens, or set --no-stream."
                            ) from exc
                        raise
            else:
                response = messages.create(**request)

        stop_reason = getattr(response, "stop_reason", "") or ""
        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise RuntimeError(f"Claude declined the review request: {details}")
        if stop_reason == "max_tokens":
            # A truncated forced tool call still yields a partial `input`, which
            # would sail through as a half-written action item and only fail
            # later, in validation, with a baffling message.
            raise TruncatedReply(
                "Claude ran out of output room after "
                f"{getattr(response.usage, 'output_tokens', '?')} tokens; "
                "raise max_tokens or review a smaller span"
            )

        payload = None
        for block in response.content:
            if block.type == "tool_use" and block.name == output.name:
                # Tool inputs arrive as parsed JSON; never string-match them.
                payload = block.input
                break
        if payload is None:
            raise RuntimeError(f"model returned no action items (stop_reason={stop_reason})")

        usage = response.usage
        return Reply(
            payload=payload,
            model=getattr(response, "model", self.model),
            usage={
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
            },
            stop_reason=stop_reason,
        )

    def propose(self, tree: ClauseTree, brief: str) -> Proposal:
        reply = self.emit(
            system=SYSTEM_PROMPT,
            cached=f"<agreement>\n{render_document(tree.root, tree)}\n</agreement>",
            variable=f"<review_brief>\n{brief}\n</review_brief>",
            output=ACTION_OUTPUT,
        )
        return _proposal_from(reply, source="claude")


def _proposal_from(reply: Reply, source: str) -> Proposal:
    return Proposal(
        action_items=normalize_items(reply.payload.get("action_items", [])),
        summary=reply.payload.get("summary", ""),
        source=source,
        model=reply.model,
        usage=reply.usage,
    )


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------
class OpenAIReviewer:
    """Generates action items with OpenAI, constrained by structured outputs.

    Uses the Responses API with ``text.format`` set to a strict ``json_schema``
    -- the same schema the Claude reviewer enforces through a forced tool call,
    so neither provider can return a shape the planner cannot execute.

    Credentials come from ``OPENAI_API_KEY`` (or ``api_key=``) exactly as the
    SDK resolves them. Install with ``pip install 'docx-redline[llm]'``.
    """

    def __init__(
        self,
        model: str = DEFAULT_OPENAI_MODEL,
        effort: str = "high",
        max_tokens: int = 16000,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any = None,
        stream: bool = True,
        timeout: float | None = 300.0,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self._client = client
        self._api_key = api_key
        self._base_url = base_url
        #: See ClaudeReviewer.stream -- same reasoning, same default.
        self.stream = stream
        self.timeout = timeout

    @property
    def client(self):
        if self._client is None:
            try:
                import openai
            except ImportError as exc:  # pragma: no cover - depends on install
                raise RuntimeError(
                    "the OpenAI reviewer needs the openai SDK: pip install openai"
                ) from exc
            options = {}
            if self._api_key:
                options["api_key"] = self._api_key
            if self._base_url:
                options["base_url"] = self._base_url
            with self._credentials():
                self._client = openai.OpenAI(**options)
        return self._client

    @staticmethod
    def _credentials():
        return _credential_errors("OpenAI", "OPENAI_API_KEY", "pass base_url=... for a proxy")

    def emit(
        self,
        *,
        system: str,
        cached: str,
        variable: str,
        output: OutputSchema,
        max_tokens: int | None = None,
        effort: str | None = None,
        cache_key: str | None = None,
        on_event: Callable[[str], None] | None = None,
    ) -> Reply:
        """One structured-output round trip.

        ``cache_key`` must be derived from ``cached`` alone, never from
        ``variable``: keying on the varying part gives every request its own
        cache partition and defeats prefix caching entirely.
        """
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": [{"role": "user", "content": f"{cached}\n\n{variable}"}],
            "text": output.text_format(),
            "reasoning": {"effort": effort or self.effort},
            "max_output_tokens": max_tokens or self.max_tokens,
            "prompt_cache_key": cache_key or f"docx-redline:{_fingerprint(cached)}",
            "store": False,
        }
        if self.timeout is not None:
            request["timeout"] = self.timeout
        with self._credentials():
            if self.stream:
                with self.client.responses.stream(**request) as live:
                    for event in live:
                        if on_event:
                            on_event(getattr(event, "type", "event"))
                    try:
                        response = live.get_final_response()
                    except RuntimeError as exc:
                        if "completed" in str(exc).lower() or "final" in str(exc).lower():
                            raise StreamInterrupted(
                                f"the response stream ended before the model finished ({exc}). "
                                "Lower --effort, reduce --segment-tokens, or set --no-stream."
                            ) from exc
                        raise
            else:
                response = self.client.responses.create(**request)
        return Reply(
            payload=_openai_payload(response),
            model=getattr(response, "model", self.model),
            usage=_openai_usage(getattr(response, "usage", None)),
            stop_reason=getattr(response, "status", "") or "",
        )

    def propose(self, tree: ClauseTree, brief: str) -> Proposal:
        reply = self.emit(
            system=SYSTEM_PROMPT,
            cached=f"<agreement>\n{render_document(tree.root, tree)}\n</agreement>",
            variable=f"<review_brief>\n{brief}\n</review_brief>",
            output=ACTION_OUTPUT,
        )
        return _proposal_from(reply, source="openai")


def _openai_payload(response: Any) -> dict:
    """Pull the structured JSON out of a Responses API result.

    Three things have to be checked before the text is trusted: an explicit
    refusal (which arrives as a content block, not an exception), a truncated
    response (``status == "incomplete"``, where the JSON would be cut mid-token
    and parse would fail with a confusing error), and an empty output.
    """
    refusal = _openai_refusal(response)
    if refusal:
        raise RuntimeError(f"the model declined the review request: {refusal}")

    status = getattr(response, "status", None)
    if status == "incomplete":
        reason = getattr(getattr(response, "incomplete_details", None), "reason", "unknown")
        message = (
            f"the model ran out of room before finishing ({reason}); "
            "raise max_tokens or review a smaller span"
        )
        if reason == "max_output_tokens":
            raise TruncatedReply(message)
        raise RuntimeError(message)

    text = getattr(response, "output_text", None) or ""
    if not text.strip():
        raise RuntimeError(f"the model returned no action items (status={status})")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"the model returned text that is not valid JSON: {exc}") from exc


def _openai_refusal(response: Any) -> str | None:
    for item in getattr(response, "output", None) or []:
        for block in getattr(item, "content", None) or []:
            if getattr(block, "type", None) == "refusal":
                return getattr(block, "refusal", "") or "no reason given"
    return None


def _openai_usage(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    details = getattr(usage, "input_tokens_details", None)
    return {
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "cached_input_tokens": getattr(details, "cached_tokens", 0) if details else 0,
    }


def _fingerprint(text: str) -> str:
    """Short stable digest, used only as a cache-routing key."""
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


#: Back-compat alias.
_outline_fingerprint = _fingerprint


# ---------------------------------------------------------------------------
# offline
# ---------------------------------------------------------------------------
class RuleBasedReviewer:
    """Deterministic stand-in for the model.

    It reads the same outline and emits the same action-item shape, chosen so
    that a run exercises every action type -- including the structural ones
    whose renumbering cascade is the interesting part.
    """

    def propose(self, tree: ClauseTree, brief: str) -> Proposal:
        items: list[dict] = []
        counter = iter(range(1, 100))

        def add(**item) -> None:
            item.setdefault("id", f"AI-{next(counter):03d}")
            items.append(item)

        payment = _clause_matching(tree, "thirty (30) days")
        if payment:
            add(
                type="replace_text",
                clause=payment.label,
                find="thirty (30) days",
                replace="forty-five (45) days",
                rationale="Align payment terms with our standard 45-day cycle.",
                severity="high",
            )
        late = _clause_titled(tree, "Late Payment")
        if late:
            add(
                type="rewrite_clause",
                clause=late.label,
                text=(
                    "Late Payment. Amounts not paid when due shall accrue interest at the lesser "
                    "of 1.0% per month or the maximum rate permitted by applicable law, and "
                    "Provider may suspend access to the Services for accounts more than thirty "
                    "(30) days past due, upon fifteen (15) days' prior written notice."
                ),
                rationale="Reduce default interest and extend the suspension grace period.",
                severity="high",
            )
        breach = _clause_matching(tree, "seventy-two (72) hours")
        if breach:
            add(
                type="replace_text",
                clause=breach.label,
                find="seventy-two (72) hours",
                replace="forty-eight (48) hours",
                rationale="Tighten the breach-notification window.",
                severity="critical",
            )
        cap = _clause_titled(tree, "Liability Cap")
        if cap:
            add(
                type="insert_text",
                clause=cap.label,
                anchor="TWELVE (12) MONTHS",
                position="after",
                text=" PRECEDING THE EVENT GIVING RISE TO THE CLAIM",
                rationale="Clarify the measurement period for the liability cap.",
                severity="medium",
            )
        auto = _clause_titled(tree, "Auto-Renewal")
        if auto:
            add(
                type="delete_text",
                clause=auto.label,
                find=" automatically",
                rationale="Remove automatic renewal; renewal should be affirmative.",
                severity="high",
            )
        reservation = _clause_titled(tree, "Reservation of Rights")
        if reservation:
            add(
                type="delete_clause",
                clause=reservation.label,
                rationale="Redundant with the licence grant; deleting closes the numbering gap.",
                severity="low",
            )
        governing = _clause_titled(tree, "Governing Law")
        term = _clause_titled(tree, "Term")
        if governing and term:
            add(
                type="move_clause",
                clause=governing.label,
                after_clause=term.label,
                rationale=(
                    "Surface governing law with the term provisions; the engine renumbers "
                    "both affected clause groups and every cross-reference."
                ),
                severity="medium",
            )
        # --- move to the top of a section -----------------------------
        # The exclusions frame the whole liability section, and they are cited
        # from the cap clause -- so this move exercises both the sibling shift
        # and the cross-reference rewrite that follows it.
        excluded = _clause_titled(tree, "Excluded Claims")
        if excluded and excluded.parent:
            add(
                type="move_clause",
                clause=excluded.label,
                into_section=excluded.parent.label,
                position="first",
                rationale=(
                    "The excluded claims frame the whole liability section and should "
                    "lead it; the engine renumbers the section and repoints every "
                    "cross-reference to it."
                ),
                severity="medium",
            )

        # --- reorder a section by clause number ------------------------
        # Boilerplate reads better alphabetically. Only the clauses that
        # genuinely have to move are moved.
        # Skip any clause another action already claims, so the two structural
        # actions cannot fight over the same paragraph.
        claimed = {
            item.get(key)
            for item in items
            for key in ("clause", "section", "after_clause", "before_clause", "into_section")
        }
        general = _clause_titled(tree, "Intellectual Property") or (
            tree.sections[-1] if tree.sections else None
        )
        if general and general.label not in claimed:
            movable = [c for c in general.children if c.label not in claimed]
            alphabetical = sorted(movable, key=lambda c: c.title.lower())
            if len(movable) >= 2 and [c.label for c in alphabetical] != [c.label for c in movable]:
                add(
                    type="reorder_clauses",
                    section=general.label,
                    order=[c.label for c in alphabetical],
                    rationale=(
                        "Put this section's clauses in alphabetical order so the "
                        "boilerplate is navigable; numbering follows the new order."
                    ),
                    severity="low",
                )

        uptime = _clause_titled(tree, "Uptime Commitment")
        if uptime:
            add(
                type="insert_clause",
                after_clause=uptime.label,
                title="Service Credit Request Window",
                text=(
                    "Customer must request any service credit in writing within sixty (60) days "
                    "of the end of the affected calendar month."
                ),
                rationale="Give Customer a longer window than the Exhibit B default.",
                severity="medium",
            )
        if tree.sections:
            add(
                type="insert_section",
                after_section=tree.sections[-1].label,
                title="Insurance",
                text=(
                    "Provider shall maintain cyber-liability and professional-indemnity "
                    "insurance of not less than $5,000,000 per occurrence throughout the "
                    "Subscription Term."
                ),
                rationale="Standard insurance covenant is missing from the agreement.",
                severity="medium",
            )
        if governing:
            add(
                type="format_text",
                clause=governing.label,
                find="Delaware",
                bold=True,
                color="C00000",
                rationale="Flag the governing-law jurisdiction for the deal team.",
                severity="low",
            )
        if breach:
            add(
                type="format_clause",
                clause=breach.label,
                space_after=18,
                rationale="Give the breach-notification clause room to breathe.",
                severity="low",
            )
        if _has_table(tree):
            add(
                type="update_cell",
                table=0,
                row=1,
                col=0,
                text="Name (please print)",
                rationale="Signature block wording is ambiguous.",
                severity="low",
            )
        if cap:
            add(
                type="comment",
                clause=cap.label,
                text="Confirm the cap multiple with finance before signature.",
                rationale="Open point for the deal team.",
                severity="medium",
            )
        return Proposal(
            action_items=items,
            summary=(
                "Customer-side markup: longer payment terms, softer late-payment remedies, "
                "tighter breach notice, no automatic renewal, and an added insurance covenant. "
                "One clause is relocated and one deleted, which cascades through the numbering."
            ),
            source="rule-based",
        )


def _has_table(tree: ClauseTree) -> bool:
    from ..oxml.ns import qn

    return next(tree.root.iter(qn("w:tbl")), None) is not None


def _clause_matching(tree: ClauseTree, needle: str):
    for clause in tree:
        if needle in clause.text:
            return clause
    return None


def _clause_titled(tree: ClauseTree, title: str):
    lowered = title.lower()
    for clause in tree:
        if clause.title.lower() == lowered:
            return clause
    for clause in tree:
        if clause.title.lower().startswith(lowered):
            return clause
    return None


# ---------------------------------------------------------------------------
#: reviewer name (and its aliases) -> constructor
REVIEWERS: dict[str, Any] = {
    "claude": ClaudeReviewer,
    "anthropic": ClaudeReviewer,
    "openai": OpenAIReviewer,
    "gpt": OpenAIReviewer,
    "rules": RuleBasedReviewer,
    "offline": RuleBasedReviewer,
    "stub": RuleBasedReviewer,
}


#: The names the CLI offers. `chunked` registers itself on import (see below).
REVIEWER_CHOICES = ("rules", "claude", "openai", "chunked")


def get_reviewer(name: str, **kwargs) -> Reviewer:
    """Build a reviewer by name: ``claude``, ``openai``, or ``rules``.

    ``rules`` takes no options; the model-backed ones accept ``model``,
    ``effort``, ``max_tokens``, ``api_key`` and an injected ``client``.
    """
    if name not in REVIEWERS:
        # `chunked` lives in a module that imports this one, so it can only
        # register itself once imported. Do that lazily rather than fail.
        with contextlib.suppress(ImportError):  # pragma: no cover - defensive
            __import__(f"{__package__}.chunked")
    try:
        factory = REVIEWERS[name]
    except KeyError:
        raise ValueError(
            f"unknown reviewer {name!r}; expected one of {sorted(set(REVIEWERS))}"
        ) from None
    if factory is RuleBasedReviewer:
        return RuleBasedReviewer()
    return factory(**kwargs)


def default_model_for(name: str) -> str | None:
    """The model a named reviewer would use if not told otherwise."""
    factory = REVIEWERS.get(name)
    if factory is None and name in REVIEWER_CHOICES:
        __import__(f"{__package__}.chunked")
        factory = REVIEWERS.get(name)
    return {
        ClaudeReviewer: DEFAULT_CLAUDE_MODEL,
        OpenAIReviewer: DEFAULT_OPENAI_MODEL,
    }.get(
        factory,
        DEFAULT_CLAUDE_MODEL
        if factory is not None and factory.__name__ == "ChunkedReviewer"
        else None,
    )


def load_proposal(path) -> Proposal:
    """Read an action-item file produced by either reviewer."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        items, summary, source = data, "", "file"
    else:
        items = data.get("action_items", data.get("operations", []))
        summary = data.get("summary", "")
        source = data.get("generated_by", "file")
    items = normalize_items(items)
    problems = validate_actions(items)
    if problems:
        raise ValueError("invalid action items in {}:\n  {}".format(path, "\n  ".join(problems)))
    return Proposal(action_items=items, summary=summary, source=source)
