"""16 · Structured model output.

    validate_edits(payload) -> list[str]        schema only, no document access
    load_edits(payload, strict=True) -> list[RedlineEdit | ReviewNote]

strict=True raises rather than silently dropping items: a dropped finding is a
review that quietly did less than it claimed.
"""

import json

from _shared import banner, fresh, section

from docx_redline import (
    ParagraphIndex,
    RedlineError,
    ReviewNote,
    load_edits,
    validate_edits,
)

banner("16 · Model output")

GOOD = json.loads("""[
  {"kind": "edit", "para_id": 19,
   "target": "thirty (30) days", "replacement": "forty-five (45) days",
   "agent": "payment-terms", "severity": "high",
   "rationale": "Net 45 matches our AP cycle."},

  {"kind": "edit", "para_id": 19,
   "target": "of the invoice date", "replacement": "of receipt of a valid invoice",
   "agent": "payment-terms", "severity": "low", "occurrence": 1,
   "insertion_first": false, "rationale": "Invoices are dated before they are sent."},

  {"kind": "note", "para_id": 15,
   "target": "reverse engineer, decompile, or disassemble",
   "body": "No carve-out for interoperability. Check local law.",
   "agent": "IP", "severity": "medium", "occurrence": 1}
]""")

section("kind defaults to 'edit'; every field is optional except para_id/target")
items = load_edits(GOOD)
for item in items:
    print(f"  {type(item).__name__:<12} p{item.para_id} {item.target[:34]!r} [{item.agent}]")

section("straight into apply()")
rl = fresh()
index = ParagraphIndex(rl)
print(index.apply(items).summary())

section("validate_edits — every problem it catches")
BAD = [
    {"para_id": 0, "target": "x", "replacment": "y"},  # typo'd key
    {"para_id": 0, "target": "x"},  # no replacement
    {"kind": "note", "para_id": 0, "target": "x"},  # note with no body
    {"kind": "annotation", "para_id": 0, "target": "x"},  # unknown kind
    {"para_id": 0, "target": "", "replacement": "y"},  # empty target
    {"para_id": 0, "target": "x", "replacement": "y", "severity": "urgent"},
    {"para_id": 0, "target": "x", "replacement": "y", "occurrence": -1},
    {"para_id": 0, "target": "x", "replacement": "y", "occurrence": "two"},
]
for problem in validate_edits(BAD):
    print("  ", problem)

section("strict=True (the default) refuses the whole batch")
try:
    load_edits(BAD)
except RedlineError as exc:
    print("  RedlineError:", str(exc).splitlines()[0])
    print("  ", len(str(exc).splitlines()) - 1, "problems listed")

section("strict=False keeps what parsed, drops what did not")
mixed = [*GOOD, {"kind": "annotation", "para_id": 0, "target": "x"}]
kept = load_edits(mixed, strict=False)
print(f"  {len(mixed)} in -> {len(kept)} out:", [type(i).__name__ for i in kept])

section("a clean payload validates to nothing")
print("  validate_edits(GOOD) ->", validate_edits(GOOD) or "no problems")

section("round-tripping the report back to JSON")
rl = fresh()
index = ParagraphIndex(rl)
report = index.apply([*load_edits(GOOD), ReviewNote(19, "no such phrase", "orphan note")])
print(json.dumps(report.to_dict(), indent=2)[:520], "...")
