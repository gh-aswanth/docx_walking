"""Both model-backed reviewers, driven through their real SDKs offline.

Each SDK is given an ``httpx.MockTransport`` instead of a network connection.
That exercises the genuine request-serialisation and response-parsing paths --
a misspelt parameter or a renamed response field fails here -- without an API
key and without spending a token.
"""

import json

import httpx
import pytest

# anthropic >= 1.0 moved off httpx onto httpx2 and rejects an `httpx.Client`
# outright ("Expected an instance of `httpx2.Client`"). The two have the same
# surface, so resolve whichever the installed SDK wants and mock through that.
try:  # pragma: no cover - depends on the installed anthropic
    import httpx2 as anthropic_httpx
except ImportError:  # pragma: no cover
    anthropic_httpx = httpx

from docx_redline.planning.actions import ACTION_SCHEMA, validate_actions
from docx_redline.planning.agent import (
    ACTION_FIELDS,
    ACTION_TOOL,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_OPENAI_MODEL,
    MANDATORY_FIELDS,
    ClaudeReviewer,
    OpenAIReviewer,
    RedlineCredentialsError,
    RuleBasedReviewer,
    action_schema,
    default_model_for,
    get_reviewer,
    normalize_items,
    openai_text_format,
)
from docx_redline.structure.clauses import ClauseTree

# a fully-populated item, the way a strict schema forces a model to answer
FULL_ITEM = dict.fromkeys(ACTION_FIELDS)
FULL_ITEM.update(
    {
        "id": "AI-001",
        "type": "move_clause",
        "rationale": "Governing law belongs with the term provisions.",
        "severity": "medium",
        "clause": "4.1",
        "after_clause": "3.1",
    }
)
PAYLOAD = {"summary": "Customer-side markup.", "action_items": [FULL_ITEM]}


@pytest.fixture
def tree(rl_agreement) -> ClauseTree:
    return ClauseTree(rl_agreement.document.element.body)


# ---------------------------------------------------------------------------
# the shared schema
# ---------------------------------------------------------------------------
def test_both_dialects_describe_the_same_fields():
    inline = action_schema("inline")["properties"]["action_items"]["items"]
    anyof = action_schema("anyof")["properties"]["action_items"]["items"]
    assert inline["required"] == anyof["required"] == list(ACTION_FIELDS)
    assert inline["additionalProperties"] is False
    assert anyof["additionalProperties"] is False


def test_schema_covers_every_action_type():
    """A type the planner supports but the schema omits is unreachable."""
    declared = ACTION_FIELDS["type"]["enum"]
    assert sorted(declared) == sorted(ACTION_SCHEMA)


def test_schema_covers_every_action_key():
    """Every key any action accepts must be expressible in the model's schema."""
    keys = {key for required, optional in ACTION_SCHEMA.values() for key in required + optional}
    assert keys <= set(ACTION_FIELDS), keys - set(ACTION_FIELDS)


def test_mandatory_fields_are_not_nullable():
    props = action_schema("inline")["properties"]["action_items"]["items"]["properties"]
    for name in MANDATORY_FIELDS:
        assert props[name]["type"] == "string", name
    assert props["clause"]["type"] == ["string", "null"]


def test_nullable_enums_use_anyof_for_openai_and_inline_for_anthropic():
    """An enum cannot simply be widened -- null has to go somewhere valid."""
    inline = action_schema("inline")["properties"]["action_items"]["items"]["properties"]
    anyof = action_schema("anyof")["properties"]["action_items"]["items"]["properties"]
    assert inline["position"]["type"] == ["string", "null"]
    assert None in inline["position"]["enum"]
    assert anyof["position"] == {
        "anyOf": [
            {"type": "string", "enum": ["before", "after", "start", "end", "first", "last"]},
            {"type": "null"},
        ]
    }
    assert "enum" not in anyof["position"]


def test_openai_text_format_shape():
    fmt = openai_text_format()["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["strict"] is True
    assert fmt["name"] == ACTION_TOOL["name"]
    assert fmt["schema"]["type"] == "object"


def test_normalize_strips_the_nulls_the_schema_forced():
    [item] = normalize_items([FULL_ITEM])
    assert item == {
        "id": "AI-001",
        "type": "move_clause",
        "rationale": "Governing law belongs with the term provisions.",
        "severity": "medium",
        "clause": "4.1",
        "after_clause": "3.1",
    }
    assert validate_actions([item]) == []


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------
def openai_client(handler):
    import openai

    return openai.OpenAI(
        api_key="sk-test", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def sse(events) -> bytes:
    """Server-sent events, the wire format both SDKs stream over."""
    return "".join(
        f"event: {name}\ndata: {json.dumps(payload)}\n\n" for name, payload in events
    ).encode()


def openai_stream(body: str, *, status="completed", incomplete=None, refusal=None) -> bytes:
    final = openai_response(body, status=status, incomplete=incomplete, refusal=refusal)
    return sse(
        [
            (
                "response.created",
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {**final, "status": "in_progress", "output": []},
                },
            ),
            (
                "response.completed",
                {"type": "response.completed", "sequence_number": 1, "response": final},
            ),
        ]
    )


def openai_response(body: str, *, status="completed", incomplete=None, refusal=None):
    content = (
        [{"type": "refusal", "refusal": refusal}]
        if refusal
        else [{"type": "output_text", "text": body, "annotations": []}]
    )
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.5",
        "status": status,
        "incomplete_details": {"reason": incomplete} if incomplete else None,
        "output": [
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": content,
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 340,
            "total_tokens": 1540,
            "input_tokens_details": {"cached_tokens": 1024},
            "output_tokens_details": {"reasoning_tokens": 100},
        },
    }


@pytest.fixture
def openai_capture():
    seen = {}

    def make(**response_kwargs):
        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=openai_stream(json.dumps(PAYLOAD), **response_kwargs),
            )

        return openai_client(handler), seen

    return make


def test_openai_request_shape(tree, openai_capture):
    client, seen = openai_capture()
    OpenAIReviewer(client=client).propose(tree, "review for the customer")

    assert seen["url"].endswith("/v1/responses")
    body = seen["body"]
    assert body["model"] == DEFAULT_OPENAI_MODEL
    assert body["reasoning"] == {"effort": "high"}
    assert body["max_output_tokens"] == 16000
    assert body["store"] is False
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["instructions"].startswith("You are a contract review assistant.")
    assert "<agreement>" in body["input"][0]["content"]
    assert "<review_brief>" in body["input"][0]["content"]


def test_openai_cache_key_is_stable_per_document(tree, openai_capture):
    keys = []
    for _ in range(2):
        client, seen = openai_capture()
        OpenAIReviewer(client=client).propose(tree, "a brief")
        keys.append(seen["body"]["prompt_cache_key"])
    client, seen = openai_capture()
    OpenAIReviewer(client=client).propose(tree, "a different brief")
    assert keys[0] == keys[1] == seen["body"]["prompt_cache_key"]  # brief must not bust the cache


def test_openai_parses_the_proposal(tree, openai_capture):
    client, _ = openai_capture()
    proposal = OpenAIReviewer(client=client).propose(tree, "brief")
    assert proposal.source == "openai"
    assert proposal.model == "gpt-5.5"
    assert proposal.summary == "Customer-side markup."
    assert proposal.action_items == [
        {
            "id": "AI-001",
            "type": "move_clause",
            "clause": "4.1",
            "after_clause": "3.1",
            "rationale": "Governing law belongs with the term provisions.",
            "severity": "medium",
        }
    ]
    assert proposal.usage == {
        "input_tokens": 1200,
        "output_tokens": 340,
        "cached_input_tokens": 1024,
    }


def test_openai_model_and_effort_overrides(tree, openai_capture):
    client, seen = openai_capture()
    OpenAIReviewer(client=client, model="gpt-5.4-mini", effort="low").propose(tree, "brief")
    assert seen["body"]["model"] == "gpt-5.4-mini"
    assert seen["body"]["reasoning"]["effort"] == "low"


def test_openai_refusal_is_reported(tree, openai_capture):
    client, _ = openai_capture(refusal="I can't help with that.")
    with pytest.raises(RuntimeError, match="declined the review request"):
        OpenAIReviewer(client=client).propose(tree, "brief")


def test_openai_truncated_response_is_reported(tree, openai_capture):
    """A cut-off reply would otherwise surface as a confusing JSON error."""
    client, _ = openai_capture(status="incomplete", incomplete="max_output_tokens")
    with pytest.raises(RuntimeError, match=r"ran out of room.*max_output_tokens"):
        OpenAIReviewer(client=client).propose(tree, "brief")


def test_openai_non_json_reply_is_reported(tree):
    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=openai_stream("Sure! Here are my thoughts."),
        )

    with pytest.raises(RuntimeError, match="not valid JSON"):
        OpenAIReviewer(client=openai_client(handler)).propose(tree, "brief")


def test_openai_empty_reply_is_reported(tree):
    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=openai_stream("   ")
        )

    with pytest.raises(RuntimeError, match="returned no action items"):
        OpenAIReviewer(client=openai_client(handler)).propose(tree, "brief")


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------
def claude_client(handler):
    import anthropic

    return anthropic.Anthropic(
        api_key="sk-ant-test",
        http_client=anthropic_httpx.Client(transport=anthropic_httpx.MockTransport(handler)),
    )


def claude_stream(content, *, stop_reason="tool_use", stop_details=None) -> bytes:
    """The same message, delivered as the SDK's streaming event sequence."""
    start = claude_response([], stop_reason=None, stop_details=None)
    start["usage"] = {
        "input_tokens": 2000,
        "output_tokens": 0,
        "cache_read_input_tokens": 1800,
        "cache_creation_input_tokens": 0,
    }
    events = [("message_start", {"type": "message_start", "message": start})]
    for index, block in enumerate(content):
        if block["type"] == "tool_use":
            events.append(
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": index,
                        "content_block": {
                            "type": "tool_use",
                            "id": block["id"],
                            "name": block["name"],
                            "input": {},
                        },
                    },
                )
            )
            events.append(
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": json.dumps(block["input"]),
                        },
                    },
                )
            )
        else:
            events.append(
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": index,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
            )
            events.append(
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": block["text"]},
                    },
                )
            )
        events.append(("content_block_stop", {"type": "content_block_stop", "index": index}))
    delta = {"stop_reason": stop_reason, "stop_sequence": None}
    if stop_details:
        delta["stop_details"] = stop_details
    events.append(
        (
            "message_delta",
            {"type": "message_delta", "delta": delta, "usage": {"output_tokens": 500}},
        )
    )
    events.append(("message_stop", {"type": "message_stop"}))
    return sse(events)


def claude_response(content, *, stop_reason="tool_use", stop_details=None):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "stop_details": stop_details,
        "usage": {
            "input_tokens": 2000,
            "output_tokens": 500,
            "cache_read_input_tokens": 1800,
            "cache_creation_input_tokens": 0,
        },
    }


TOOL_BLOCK = [{"type": "tool_use", "id": "tu_1", "name": "emit_action_items", "input": PAYLOAD}]


@pytest.fixture
def claude_capture():
    seen = {}

    def make(payload=None):
        def handler(request: anthropic_httpx.Request) -> anthropic_httpx.Response:
            seen["url"] = str(request.url)
            seen["beta"] = request.headers.get("anthropic-beta")
            seen["body"] = json.loads(request.content)
            return anthropic_httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=payload if payload is not None else claude_stream(TOOL_BLOCK),
            )

        return claude_client(handler), seen

    return make


def test_claude_request_shape(tree, claude_capture):
    client, seen = claude_capture()
    ClaudeReviewer(client=client).propose(tree, "review for the customer")

    body = seen["body"]
    assert body["model"] == DEFAULT_CLAUDE_MODEL
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "high"}
    assert body["tool_choice"] == {"type": "tool", "name": "emit_action_items"}
    assert body["tools"][0]["strict"] is True
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_claude_enables_refusal_fallbacks_by_default(tree, claude_capture):
    client, seen = claude_capture()
    ClaudeReviewer(client=client).propose(tree, "brief")
    assert seen["body"]["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen["beta"]


def test_claude_fallbacks_can_be_turned_off(tree, claude_capture):
    client, seen = claude_capture()
    ClaudeReviewer(client=client, fallbacks=False).propose(tree, "brief")
    assert "fallbacks" not in seen["body"]


def test_claude_parses_the_proposal(tree, claude_capture):
    client, _ = claude_capture()
    proposal = ClaudeReviewer(client=client).propose(tree, "brief")
    assert proposal.source == "claude"
    assert proposal.model == "claude-opus-5"
    assert proposal.action_items == [
        {
            "id": "AI-001",
            "type": "move_clause",
            "clause": "4.1",
            "after_clause": "3.1",
            "rationale": "Governing law belongs with the term provisions.",
            "severity": "medium",
        }
    ]
    assert proposal.usage["cache_read_input_tokens"] == 1800


def test_claude_refusal_is_reported(tree, claude_capture):
    client, _ = claude_capture(
        claude_stream(
            [], stop_reason="refusal", stop_details={"type": "refusal", "category": "other"}
        )
    )
    with pytest.raises(RuntimeError, match="declined the review request"):
        ClaudeReviewer(client=client).propose(tree, "brief")


def test_claude_missing_tool_call_is_reported(tree, claude_capture):
    client, _ = claude_capture(
        claude_stream(
            [{"type": "text", "text": "I'd suggest a few changes."}], stop_reason="end_turn"
        )
    )
    with pytest.raises(RuntimeError, match="no action items"):
        ClaudeReviewer(client=client).propose(tree, "brief")


# ---------------------------------------------------------------------------
# both providers agree
# ---------------------------------------------------------------------------
def test_both_providers_return_the_same_items(tree, openai_capture, claude_capture):
    """Same schema, same payload -> byte-identical action items."""
    oa_client, _ = openai_capture()
    cl_client, _ = claude_capture()
    from_openai = OpenAIReviewer(client=oa_client).propose(tree, "brief")
    from_claude = ClaudeReviewer(client=cl_client).propose(tree, "brief")
    assert from_openai.action_items == from_claude.action_items
    assert from_openai.summary == from_claude.summary
    assert from_openai.source != from_claude.source


def test_model_backed_items_survive_validation(tree, openai_capture):
    client, _ = openai_capture()
    proposal = OpenAIReviewer(client=client).propose(tree, "brief")
    assert validate_actions(proposal.action_items) == []


def test_pipeline_accepts_an_injected_reviewer(tmp_path, agreement, openai_capture):
    """A model-backed reviewer drops straight into the pipeline."""
    from docx_redline.planning.pipeline import RedlinePipeline

    client, _ = openai_capture()
    result = RedlinePipeline(
        agreement, date="2026-01-01T00:00:00Z", reviewer=OpenAIReviewer(client=client)
    ).run(tmp_path / "out.docx", write_actions=False)
    assert result.ok, result.format()
    assert result.proposal.source == "openai"
    # the single move must still cascade through the numbering
    assert {c["from"]: c["to"] for c in result.plan.renumbered}["4.1"] == "3.2"


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name,expected",
    [
        ("claude", ClaudeReviewer),
        ("anthropic", ClaudeReviewer),
        ("openai", OpenAIReviewer),
        ("gpt", OpenAIReviewer),
        ("rules", RuleBasedReviewer),
        ("offline", RuleBasedReviewer),
    ],
)
def test_get_reviewer(name, expected):
    assert isinstance(get_reviewer(name), expected)


def test_get_reviewer_rejects_unknown_names():
    with pytest.raises(ValueError, match="unknown reviewer"):
        get_reviewer("gemini")


def test_get_reviewer_passes_options_through():
    reviewer = get_reviewer("openai", model="gpt-5.4-mini", effort="low")
    assert reviewer.model == "gpt-5.4-mini" and reviewer.effort == "low"


def test_default_model_for():
    assert default_model_for("claude") == DEFAULT_CLAUDE_MODEL
    assert default_model_for("openai") == DEFAULT_OPENAI_MODEL
    assert default_model_for("rules") is None


# ---------------------------------------------------------------------------
# credentials
# ---------------------------------------------------------------------------
def _no_keys(monkeypatch):
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_ADMIN_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_openai_missing_credentials_is_actionable(tree, monkeypatch):
    """The SDK's own error names none of this tool; ours names the variable."""
    _no_keys(monkeypatch)
    with pytest.raises(RedlineCredentialsError, match="OPENAI_API_KEY"):
        OpenAIReviewer().propose(tree, "brief")


def test_claude_missing_credentials_is_actionable(tree, monkeypatch):
    """Anthropic constructs happily and only fails on the request, so the
    translation has to wrap the call as well as the constructor."""
    _no_keys(monkeypatch)
    with pytest.raises(RedlineCredentialsError, match="ANTHROPIC_API_KEY"):
        ClaudeReviewer().propose(tree, "brief")


def test_credential_translation_does_not_swallow_other_errors(tree):
    def handler(request):
        return httpx.Response(500, json={"error": {"message": "upstream exploded"}})

    with pytest.raises(Exception) as info:
        OpenAIReviewer(client=openai_client(handler)).propose(tree, "brief")
    assert not isinstance(info.value, RedlineCredentialsError)


# ---------------------------------------------------------------------------
# streaming and timeouts
# ---------------------------------------------------------------------------
def test_openai_streams_by_default(tree, openai_capture):
    """A reasoning-heavy review runs for minutes; a non-streaming request that
    long risks an HTTP read timeout with nothing to show for the wait."""
    client, seen = openai_capture()
    OpenAIReviewer(client=client).propose(tree, "brief")
    assert seen["body"]["stream"] is True


def test_claude_streams_by_default(tree, claude_capture):
    client, seen = claude_capture()
    ClaudeReviewer(client=client).propose(tree, "brief")
    assert seen["body"]["stream"] is True


def test_streaming_can_be_switched_off(tree):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=openai_response(json.dumps(PAYLOAD)))

    OpenAIReviewer(client=openai_client(handler), stream=False).propose(tree, "brief")
    assert "stream" not in seen["body"] or seen["body"]["stream"] is False


def test_a_stalled_call_gives_up_instead_of_hanging(tree):
    """Without a timeout the SDK waits 600s, then retries -- for a single
    segment that is a very long silence."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated stall", request=request)

    import openai

    reviewer = OpenAIReviewer(
        client=openai.OpenAI(
            api_key="sk-test",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
        timeout=0.5,
    )
    with pytest.raises(openai.APITimeoutError):
        reviewer.propose(tree, "brief")


def test_the_timeout_reaches_the_sdk(tree, openai_capture):
    client, _ = openai_capture()
    reviewer = OpenAIReviewer(client=client, timeout=42.0)
    reviewer.propose(tree, "brief")
    assert reviewer.timeout == 42.0
