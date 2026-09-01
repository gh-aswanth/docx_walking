"""22 · Declarative op plans — the low-level JSON layer.

    validate(operations) -> list[str]
    apply_operations(rl, operations, strict=True) -> list[OpResult]

No clause awareness, no renumbering. Use this when a rules engine already knows
exactly which paragraphs to touch.
"""

from _shared import banner, fresh, save, section

from docx_redline import RedlineError
from docx_redline.editing.ops import _HANDLERS, apply_operations, validate

banner("22 · Declarative op plans")

PLAN = {
    "operations": [
        {
            "op": "replace_text",
            "old": "thirty (30) days",
            "new": "forty-five (45) days",
            "count": None,
        },
        {
            "op": "insert_text",
            "match": "of the invoice date",
            "text": ", without setoff or deduction",
            "where": "after",
        },
        {"op": "delete_text", "match": " automatically", "count": 1},
        {
            "op": "insert_paragraph",
            "match": "3.4  Taxes",
            "text": "3.5  Currency. All amounts are payable in U.S. dollars.",
            "where": "after",
        },
        {"op": "delete_paragraph", "match": "Reservation of Rights"},
        {
            "op": "update_paragraph",
            "match": "4.3  Termination for Cause",
            "text": "4.3  Termination for Cause. Either Party may terminate on 15 days' notice.",
        },
        {"op": "move_paragraph", "match": "12.1  Governing Law", "after": "4.1  Term."},
        {"op": "insert_row", "table": 0, "values": ["Countersigned by", "Date"]},
        {"op": "delete_row", "table": 1, "row": 1},
        {"op": "update_cell", "table": 0, "row": 1, "col": 0, "text": "Name (please print)"},
        {"op": "format_text", "match": "Delaware", "bold": True, "color": "C00000"},
        {"op": "format_paragraph", "match": "6.4  Breach Notification", "alignment": "JUSTIFY"},
        {"op": "comment", "match": "10.2  Liability Cap", "text": "Confirm the cap with finance."},
    ]
}

section("every op type the layer supports")
print("  ", ", ".join(sorted(_HANDLERS)))

section("validate — dry-run the plan before touching the file")
print("  clean plan ->", validate(PLAN["operations"]) or "no problems")
for problem in validate(
    [
        {"op": "replace_txt", "old": "a", "new": "b"},
        {"op": "replace_text", "old": "a"},
        {"match": "a", "text": "b"},
    ]
):
    print("  ", problem)

section("apply_operations — one OpResult per op")
rl = fresh()
for result in apply_operations(rl, PLAN["operations"]):
    print(f"  {result.op:<18} x{result.applied:<3} {result.detail}")

section("the shared keys")
print("""  match       substring, or a regex if the substring finds nothing
  occurrence  0-based index when `match` hits several paragraphs
  count       how many replacements/deletions; null for all
  regex       treat `old`/`match` as a pattern
  ignore_case matching flag on the text ops
  where       insert_text: before | after | end
              insert_paragraph: before | after""")

section("occurrence — pick which matching paragraph")
print("  'thirty (30) days' appears in 4 paragraphs; occurrence picks one:")
for occ in (0, 1, 2, 3):
    rl = fresh()
    apply_operations(
        rl, [{"op": "delete_paragraph", "match": "thirty (30) days", "occurrence": occ}]
    )
    struck = next(r.text for r in rl.summary().revisions if r.kind == "delete")
    print(f"  occurrence={occ} -> struck {struck[:52]!r}")

section("strict — raise on an op that matches nothing, or carry on")
BROKEN = [{"op": "replace_text", "old": "not in the document", "new": "x"}]
try:
    apply_operations(fresh(), BROKEN, strict=True)
except RedlineError as exc:
    print("  strict=True  -> RedlineError:", str(exc)[:60])
results = apply_operations(fresh(), BROKEN, strict=False)
print(f"  strict=False -> {results[0].op} x{results[0].applied} (recorded, not raised)")

section("a plan file may be {'operations': [...]} or a bare list")
print("  both shapes are accepted by the CLI's `apply` command:")
print("    python -m docx_redline apply contract.docx plan.json -o out.docx [--lenient]")

rl = fresh()
apply_operations(rl, PLAN["operations"])
save(rl, "22_ops_plan.docx")
