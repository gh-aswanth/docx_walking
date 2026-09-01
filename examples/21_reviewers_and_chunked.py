"""21 · Reviewers — where action items come from.

Three reviewers, one interface. This example runs entirely offline: the
model-backed ones are constructed and inspected, never called, so no API key
is needed to read it.

    get_reviewer(name, **kwargs)      default_model_for(name)
    RuleBasedReviewer()               ClaudeReviewer(...)   OpenAIReviewer(...)
    ChunkedReviewer(engine, ...)      load_proposal(path)
"""

from _shared import PLAN, SOURCE, banner, section

from docx_redline import (
    ChunkedReviewer,
    ClaudeReviewer,
    OpenAIReviewer,
    RedlineCredentialsError,
    RedlinePipeline,
    RuleBasedReviewer,
    default_model_for,
    get_reviewer,
    load_proposal,
)
from docx_redline.planning.agent import REVIEWERS

banner("21 · Reviewers")

section("the registry")
for name in sorted(REVIEWERS):
    print(
        f"  {name:<12} -> {REVIEWERS[name].__name__:<18} default model: {default_model_for(name)}"
    )

section("the interface: propose(tree, brief) -> Proposal")
import docx

from docx_redline import ClauseTree

tree = ClauseTree(docx.Document(SOURCE).element.body)
BRIEF = "Review this agreement on behalf of the Customer."

proposal = RuleBasedReviewer().propose(tree, BRIEF)
print(f"  RuleBasedReviewer -> {len(proposal.action_items)} items, source={proposal.source!r}")
for item in proposal.action_items[:4]:
    print(f"    {item['id']} {item['type']:<16} {item.get('rationale', '')[:52]}")
print("  it is what generates the committed action_items.json")

section("get_reviewer — by name, keyword options passed straight through")


def describe(reviewer):
    name = type(reviewer).__name__
    bits = [
        f"{a}={getattr(reviewer, a)!r}"
        for a in ("model", "effort", "concurrency", "segment_tokens")
        if hasattr(reviewer, a)
    ]
    return f"{name}({', '.join(bits)})"


print(" ", describe(get_reviewer("rules")))
print(" ", describe(get_reviewer("claude", model="claude-opus-5", effort="low")))
print(" ", describe(get_reviewer("chunked", engine="claude", concurrency=8, segment_tokens=12_000)))
print("  the CLI's --provider maps onto ChunkedReviewer's `engine` argument")

section("ClaudeReviewer options")
claude = ClaudeReviewer(
    model="claude-opus-5",
    effort="high",
    max_tokens=16_000,
    api_key="not-used-here",
    fallbacks=True,
    stream=True,
    timeout=300.0,
)
for attr in ("model", "effort", "max_tokens", "stream", "timeout", "fallbacks"):
    print(f"  {attr:<12} = {getattr(claude, attr)!r}")

section("OpenAIReviewer options")
openai = OpenAIReviewer(
    model="gpt-5.5",
    effort="high",
    max_tokens=16_000,
    api_key="not-used-here",
    base_url=None,
    stream=True,
    timeout=300.0,
)
for attr in ("model", "effort", "max_tokens", "stream", "timeout"):
    print(f"  {attr:<12} = {getattr(openai, attr)!r}")

section("effort levels")
print("  low, medium, high, xhigh, max")

section("missing credentials fail loudly, naming the variable")
import os

saved = {k: os.environ.pop(k, None) for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
try:
    try:
        OpenAIReviewer().propose(tree, BRIEF)
    except RedlineCredentialsError as exc:
        print("  RedlineCredentialsError:", exc)
    except Exception as exc:
        print(f"  {type(exc).__name__}: {str(exc)[:80]}")
finally:
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v

section("ChunkedReviewer — every option, constructed but not called")
chunked = ChunkedReviewer(
    "claude",
    segment_tokens=25_000,
    index_tokens=12_000,
    concurrency=6,
    triage=True,
    triage_effort="low",
    min_coverage=0.35,
    max_actions=None,
    cache_dir=None,
    use_cache=True,
    refresh=False,
    strategy="auto",
    max_attempts=3,
    max_split_depth=2,
    backoff=1.0,
    on_progress=None,
)
for attr in (
    "engine",
    "segment_tokens",
    "index_tokens",
    "concurrency",
    "triage_enabled",
    "triage_effort",
    "min_coverage",
    "max_actions",
    "strategy",
    "max_attempts",
    "max_split_depth",
    "backoff",
    "on_progress",
):
    value = getattr(chunked, attr)
    value = type(value).__name__ if attr == "engine" else value
    print(f"  {attr:<16} = {value!r}")
print(
    f"  {'cache':<16} = enabled={chunked.cache.enabled!r} refresh={chunked.cache.refresh!r} "
    f"dir={chunked.cache.directory.name!r}"
)
print("  (triage= is stored as triage_enabled; use_cache/refresh/cache_dir live on .cache)")

section("what chunked does before it calls anything")
import docx

from docx_redline import build_index, segment_document

body = docx.Document(SOURCE).element.body
# the sample contract is only ~3k tokens, so squeeze the budget to show the cut
segments = segment_document(body, budget_tokens=800)
print(f"  segment_document -> {len(segments)} segments")
for seg in segments[:5]:
    print(f"    {seg.id:<10} {seg.approx_tokens:>5} tok  {seg.title[:44]}")
print("\n  build_index -> the titles-only prefix the triage call reads:")
print("\n".join("    " + line for line in build_index(segments).splitlines()[:6]))

section("load_proposal — replay a committed plan as a Proposal")
replayed = load_proposal(PLAN)
print(f"  {len(replayed.action_items)} items from {PLAN.name}")

section("wiring one into the pipeline")
print("  RedlinePipeline(src, reviewer='rules')                    # offline")
print("  RedlinePipeline(src, reviewer=ClaudeReviewer())           # ANTHROPIC_API_KEY")
print("  RedlinePipeline(src, reviewer=ChunkedReviewer('claude'))  # long documents")
pipe = RedlinePipeline(SOURCE, reviewer="rules")
pipe.extract()  # propose() reads the tree extract() builds -- call it first
print("  ->", len(pipe.propose(None).action_items), "items from the offline reviewer")
