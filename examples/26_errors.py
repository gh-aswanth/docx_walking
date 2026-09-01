"""26 · The exception hierarchy, and what raises what.

RedlineError              base: an edit could not be located or applied
  ClauseError             a clause number could not be resolved
  StalePlanError          a plan was computed against a different version
  RedlineCredentialsError a model-backed reviewer has no API key
"""

import docx
from _shared import SOURCE, banner, fresh, section

from docx_redline import (
    ClauseError,
    ClauseTree,
    ParagraphIndex,
    RedlineCredentialsError,
    RedlineEdit,
    RedlineError,
    StalePlanError,
    apply_actions,
    full_redline,
    load_edits,
    verify_plan,
)
from docx_redline.editing.ops import apply_operations

banner("26 · Errors")

section("the hierarchy")
for exc in (RedlineError, ClauseError, StalePlanError, RedlineCredentialsError):
    bases = " <- ".join(c.__name__ for c in exc.__mro__[1:4])
    print(f"  {exc.__name__:<24} {bases}")
print("  catching RedlineError catches all of them")


def raises(title, fn):
    try:
        fn()
    except Exception as exc:
        print(f"\n  {title}")
        lines = [line for line in str(exc).splitlines() if line.strip()]
        print(f"    {type(exc).__name__}: {lines[0][:96]}")
        for extra in lines[1:2]:
            print(f"      {extra.strip()[:94]}")


section("RedlineError — locating failures")
raises(
    "find_paragraph matched nothing",
    lambda: fresh().find_paragraph(contains="not in this contract"),
)
raises(
    "an unknown paragraph style",
    lambda: fresh().apply_style(fresh().find_paragraph(contains="3.2  Invoicing"), "Nonesuch"),
)
raises(
    "a strict op that matched nothing",
    lambda: apply_operations(
        fresh(), [{"op": "replace_text", "old": "absent", "new": "x"}], strict=True
    ),
)
raises("ParagraphIndex.paragraph out of range", lambda: ParagraphIndex(fresh()).paragraph(9999))
raises(
    "a malformed model payload",
    lambda: load_edits([{"para_id": 0, "target": "x", "replacment": "y"}]),
)
raises(
    "an action plan that fails its schema check",
    lambda: apply_actions(fresh(), [{"id": "X", "type": "renumber_clause", "clause": "3.1"}]),
)
raises("full_redline with nothing to do", lambda: full_redline(SOURCE, "/dev/null"))

section("ClauseError — a clause number that does not resolve")
tree = ClauseTree(docx.Document(SOURCE).element.body)
raises("a hallucinated clause number", lambda: tree.get("99.9"))
raises(
    "an action pointing at one",
    lambda: apply_actions(
        fresh(), [{"id": "X", "type": "delete_clause", "clause": "99.9"}], strict=True
    ),
)
print("    a hallucinated clause fails loudly at the plan stage, instead of")
print("    silently editing the wrong paragraph")

section("StalePlanError — the plan and the document disagree")
rl = fresh()
index = ParagraphIndex(rl)
stale = index.fingerprint()
index.apply([RedlineEdit(19, "thirty (30) days", "forty-five (45) days")])
raises("re-verifying after the document moved on", lambda: verify_plan(index, stale))

section("RedlineCredentialsError — names the variable to set")
import os

saved = {k: os.environ.pop(k, None) for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
try:
    from docx_redline import ClaudeReviewer, OpenAIReviewer

    for cls in (OpenAIReviewer, ClaudeReviewer):
        raises(cls.__name__, lambda cls=cls: cls().propose(tree, "Review this."))
finally:
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
print("\n    the two SDKs fail at different moments -- OpenAI refuses to build a")
print("    client without a key, Anthropic builds one and rejects the first")
print("    request -- so the translation wraps both")

section("recording a failure instead of raising")
report = apply_actions(
    fresh(),
    [
        {
            "id": "AI-001",
            "type": "replace_text",
            "clause": "3.2",
            "find": "thirty (30) days",
            "replace": "forty-five (45) days",
        },
        {
            "id": "AI-002",
            "type": "replace_text",
            "clause": "3.2",
            "find": "not in this clause",
            "replace": "x",
        },
    ],
    strict=False,
)
for res in report.results:
    print(f"  {res.id} {res.status:<8} {res.detail[:64]}")
print("  strict=False records; strict=True raises on the first failure")

section("and Rejection, which is data rather than an exception")
report = ParagraphIndex(fresh()).apply([RedlineEdit(6, "Provider", "Vendor")])
res = report.rejected[0]
print(f"  {res.reason!r}")
print(f"  {res.detail}")
print("  the ParagraphIndex layer reports rather than raises, so one bad edit in")
print("  a batch of forty does not lose the other thirty-nine")
