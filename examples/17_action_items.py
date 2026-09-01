"""17 · Action items — the planner and its options.

    validate_actions(items) -> list[str]              schema only
    apply_actions(rl, items, renumber=True, strict=False, explain=False)
    ActionPlanner(rl, renumber=True, strict=False, explain=False).run(items)

An action item is a review decision ("move the governing-law clause"), not an
XML edit. The planner works out the consequential edits nobody wrote down.
"""

import json

from _shared import PLAN, banner, fresh, save, section

from docx_redline import ActionPlanner, apply_actions, validate_actions

banner("17 · Action items")

ITEMS = [
    {
        "id": "AI-001",
        "type": "replace_text",
        "clause": "3.2",
        "find": "thirty (30) days",
        "replace": "forty-five (45) days",
        "rationale": "Align payment terms with our 45-day cycle.",
        "severity": "high",
    },
    {
        "id": "AI-002",
        "type": "delete_clause",
        "clause": "2.3",
        "rationale": "Redundant with the licence grant.",
        "severity": "low",
    },
    {
        "id": "AI-003",
        "type": "move_clause",
        "clause": "12.1",
        "after_clause": "4.1",
        "rationale": "Governing law belongs with the term provisions.",
        "severity": "medium",
    },
]

section("validate_actions — schema check, no document access")
print("  clean plan ->", validate_actions(ITEMS) or "no problems")
for problem in validate_actions(
    [
        {"id": "X-1", "type": "replace_txt", "find": "a", "replace": "b"},
        {"id": "X-2", "type": "replace_text", "find": "a"},
        {"id": "X-2", "type": "move_clause", "clause": "3.1"},
        {"id": "X-3", "type": "renumber_clause", "clause": "3.1"},
        {"id": "X-4", "type": "replace_text", "find": "a", "replace": "b", "severity": "urgent"},
    ]
):
    print("  ", problem)

section("apply_actions — the convenience wrapper")
rl = fresh()
report = apply_actions(rl, ITEMS)
print(report.format())

section("PlanReport — per action")
for res in report.results:
    print(f"  {res.id} {res.type:<14} {res.status:<8} x{res.edits}  {res.detail}")

section("renumber=False — the literal actions and nothing else")
rl = fresh()
plain = apply_actions(rl, ITEMS, renumber=False)
print(
    f"  renumber=True  -> {len(report.renumbered)} clauses renumbered, "
    f"{len(report.references)} references rewritten"
)
print(
    f"  renumber=False -> {len(plain.renumbered)} clauses renumbered, "
    f"{len(plain.references)} references rewritten"
)

section("explain — write each rationale into the .docx as a comment")
for flag in (False, True):
    rl = fresh()
    apply_actions(rl, ITEMS, explain=flag)
    print(f"  explain={flag!s:<5} -> {sum(1 for _ in rl.document.comments)} comment(s)")
rl = fresh()
apply_actions(rl, ITEMS, explain=True)
for c in rl.document.comments:
    print("   ", c.text[:76])

section("strict — carry on and record, or abort on the first failure")
BROKEN = [
    *ITEMS,
    {
        "id": "AI-004",
        "type": "replace_text",
        "clause": "3.2",
        "find": "a phrase that is not there",
        "replace": "x",
    },
]
rl = fresh()
lenient = apply_actions(rl, BROKEN, strict=False)
print(f"  strict=False -> {lenient.applied} applied, {lenient.failed} failed (recorded)")
for res in lenient.results:
    if res.status != "applied":
        print(f"     {res.id}: {res.status} -- {res.detail}")
try:
    apply_actions(fresh(), BROKEN, strict=True)
except Exception as exc:
    print(f"  strict=True  -> {type(exc).__name__}: {str(exc)[:64]}")

section("ActionPlanner — the same thing, when you want the object")
rl = fresh()
planner = ActionPlanner(rl, renumber=True, strict=False, explain=True)
run = planner.run(ITEMS)
print("  ", run.format().splitlines()[0])

section("to_dict() — the whole run, serialisable")
print("  summary:", json.dumps(run.to_dict()["summary"]))
print("  keys   :", list(run.to_dict()))

section("the committed plan file — 29 items, every action type")
items = json.loads(PLAN.read_text())["action_items"]
rl = fresh()
big = apply_actions(rl, items, explain=True)
print(" ", big.format().replace("\n", "\n  "))
save(rl, "17_action_items.docx")
