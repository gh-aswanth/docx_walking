"""18 · Every action type, one at a time.

Each block applies exactly one action to a clean document and prints what the
planner did with it -- including the consequences it derived on its own.
"""

from _shared import banner, fresh, section

from docx_redline import RedlineError, apply_actions, validate_actions
from docx_redline.planning.actions import ACTION_SCHEMA, DERIVED_ACTIONS, STRUCTURAL_ACTIONS

banner("18 · Action vocabulary")


def one(title, item, show_consequences=False):
    rl = fresh()
    report = apply_actions(rl, [dict(item, id=item.get("id", "AI-001"))])
    res = report.results[0]
    print(f"\n  {title}")
    print(f"    {res.status:<8} x{res.edits}  {res.detail}")
    if show_consequences:
        if report.renumbered:
            moves = ", ".join(f"{r['from']}->{r['to']}" for r in report.renumbered[:6])
            print(
                f"    renumbered  {len(report.renumbered)}: {moves}"
                f"{' ...' if len(report.renumbered) > 6 else ''}"
            )
        for ref in report.references[:3]:
            print(f"    reference   {ref['context']}")
        for warn in report.warnings:
            print(f"    warning     {warn[:88]}")
    return report


section("text actions — no structural consequence")
one(
    "replace_text (clause-scoped)",
    {
        "type": "replace_text",
        "clause": "3.2",
        "find": "thirty (30) days",
        "replace": "forty-five (45) days",
    },
)
one(
    "replace_text (all=true, document-wide)",
    {"type": "replace_text", "find": "Provider shall", "replace": "Provider will", "all": True},
)
one(
    "replace_text (regex=true)",
    {
        "type": "replace_text",
        "clause": "3.3",
        "find": r"1\.5% per month",
        "replace": "1.0% per month",
        "regex": True,
    },
)
one(
    "insert_text (anchor + position)",
    {
        "type": "insert_text",
        "clause": "3.2",
        "anchor": "of the invoice date",
        "position": "after",
        "text": ", without setoff or deduction",
    },
)
one("delete_text", {"type": "delete_text", "clause": "4.2", "find": " automatically"})
one(
    "delete_text (regex=true)",
    {
        "type": "delete_text",
        "clause": "2.2",
        "regex": True,
        "find": r"\s*\(d\) use the Services to build a competing product;",
    },
)
one(
    "rewrite_clause — number kept, body word-diffed",
    {
        "type": "rewrite_clause",
        "clause": "6.4",
        "text": "Breach Notification. Provider will notify Customer without undue delay, "
        "and in no event later than forty-eight (48) hours, after becoming aware of "
        "a confirmed security breach affecting Customer Data.",
    },
)

section("structural actions — these trigger the renumbering cascade")
one(
    "insert_clause (before_clause + title)",
    {
        "type": "insert_clause",
        "before_clause": "1.1",
        "title": "Affiliate",
        "text": "“Affiliate” means any entity under common control with a Party.",
    },
    True,
)
one(
    "insert_clause (into_section — appends to the end of a section)",
    {
        "type": "insert_clause",
        "into_section": "3",
        "title": "Currency",
        "text": "All amounts are payable in U.S. dollars.",
    },
    True,
)
one("delete_clause", {"type": "delete_clause", "clause": "2.3"}, True)
one(
    "move_clause (after_clause)",
    {"type": "move_clause", "clause": "12.1", "after_clause": "4.1"},
    True,
)
one(
    "move_clause (into_section + position='first')",
    {"type": "move_clause", "clause": "10.3", "into_section": "10", "position": "first"},
    True,
)
one(
    "move_clause (before_clause)",
    {"type": "move_clause", "clause": "7.2", "before_clause": "7.1"},
    True,
)
one(
    "reorder_clauses — only what must move, moves",
    {"type": "reorder_clauses", "section": "8", "order": ["8.1", "8.3", "8.2"]},
    True,
)
one(
    "insert_section (after_section + title + text)",
    {
        "type": "insert_section",
        "after_section": "12",
        "title": "Insurance",
        "text": "Provider will maintain cyber-liability insurance of $5,000,000.",
    },
    True,
)
one(
    "delete_section — takes its sub-clauses with it",
    {"type": "delete_section", "section": "5"},
    True,
)
one(
    "move_section (before_section)",
    {"type": "move_section", "section": "11", "before_section": "10"},
    True,
)

section("table actions")
one("insert_row", {"type": "insert_row", "table": 0, "values": ["Countersigned by", "Date"]})
one(
    "insert_row (at an index)",
    {"type": "insert_row", "table": 0, "row": 0, "values": ["Party", "Detail"]},
)
one("delete_row", {"type": "delete_row", "table": 1, "row": 1})
one(
    "update_cell",
    {"type": "update_cell", "table": 0, "row": 1, "col": 0, "text": "Name (please print)"},
)

section("presentation and annotation")
one(
    "format_text (bold + color)",
    {"type": "format_text", "clause": "12.1", "find": "Delaware", "bold": True, "color": "C00000"},
)
one(
    "format_text (italic + underline + highlight)",
    {
        "type": "format_text",
        "clause": "9.3",
        "find": "AS IS",
        "italic": True,
        "underline": True,
        "highlight": "YELLOW",
    },
)
one(
    "format_clause (alignment + spacing)",
    {
        "type": "format_clause",
        "clause": "6.4",
        "alignment": "JUSTIFY",
        "space_before": 12,
        "space_after": 18,
    },
)
one("format_clause (style)", {"type": "format_clause", "clause": "1.1", "style": "Heading 4"})
one(
    "comment (anchored on a clause)",
    {"type": "comment", "clause": "10.2", "text": "Confirm the cap with finance."},
)
one(
    "comment (anchored on a phrase, anywhere)",
    {"type": "comment", "find": "SOC 2 Type II", "text": "Is ISO 27001 also in scope?"},
)

section("targeting unnumbered content — quote it, uniquely")
one(
    "replace_text in Exhibit A (no clause number to address)",
    {
        "type": "replace_text",
        "find": "Annual Fees: $186,000, payable annually in advance",
        "replace": "Annual Fees: $186,000, payable quarterly in arrears",
    },
)

section("an ambiguous quote is refused, not applied to the first match")
one(
    "replace_text with a quote that appears twice",
    {"type": "replace_text", "find": "Order Form", "replace": "Ordering Document"},
)

section("derived actions a model must never emit")
print("  ", sorted(DERIVED_ACTIONS))
print("  letting the model renumber as well as the engine is how numbering")
print("  silently double-applies, so the planner refuses the whole batch --")
print("  before the document is opened, and regardless of strict=")
for kind in sorted(DERIVED_ACTIONS):
    item = [{"id": "X", "type": kind, "clause": "3.1"}]
    print(f"    validate_actions -> {validate_actions(item)[0]}")
    try:
        apply_actions(fresh(), item, strict=False)
    except RedlineError as exc:
        print(f"    apply_actions    -> {type(exc).__name__}, nothing written")

section("the full vocabulary, from the schema itself")
for kind, (required, optional) in sorted(ACTION_SCHEMA.items()):
    mark = "*" if kind in STRUCTURAL_ACTIONS else " "
    print(f"  {mark}{kind:<18} required={list(required)}  optional={list(optional)}")
print("\n  (* = structural: triggers renumbering and cross-reference repair)")
