"""19 · The renumbering cascade.

Contracts number their clauses in the body text, so a structural change is
never one edit. Ask for one move and the planner derives the rest.

Numbers are never computed incrementally: after all structural work is done,
ClauseTree.renumber() re-derives every number from its position and diffs that
against a snapshot taken before anything moved. One pass, so a move that shifts
two separate groups of siblings cannot double-count.
"""

from _shared import banner, fresh, save, section

from docx_redline import apply_actions

banner("19 · The renumbering cascade")


def cascade(title, items):
    rl = fresh()
    report = apply_actions(rl, items)
    print(f"\n  {title}")
    for res in report.results:
        print(f"    action      {res.id} {res.detail}")
    for r in report.renumbered:
        print(f"    {r['from']:>6} -> {r['to']:<6} {r['title'][:44]}")
    for ref in report.references:
        print(f"    reference   {ref['context']}")
    for ref in report.dangling_references:
        print(f"    DANGLING    {ref}")
    for warn in report.warnings:
        print(f"    warning     {warn[:96]}")
    return rl, report


section("one move, nine consequences")
cascade(
    "move 12.1 after 4.1",
    [
        {"id": "AI-001", "type": "move_clause", "clause": "12.1", "after_clause": "4.1"},
    ],
)

section("move to the top of a section — and the citation follows")
cascade(
    "move 10.3 to the top of section 10",
    [
        {
            "id": "AI-002",
            "type": "move_clause",
            "clause": "10.3",
            "into_section": "10",
            "position": "first",
        },
    ],
)

section("insert pushes later siblings down")
cascade(
    "insert a definition before 1.1",
    [
        {
            "id": "AI-003",
            "type": "insert_clause",
            "before_clause": "1.1",
            "title": "Affiliate",
            "text": "“Affiliate” means any entity under common control with a Party.",
        },
    ],
)

section("delete closes the ranks")
cascade("delete 2.3", [{"id": "AI-004", "type": "delete_clause", "clause": "2.3"}])

section("reorder — only what must move, moves")
cascade(
    "reorder section 8 as 8.1, 8.3, 8.2",
    [
        {"id": "AI-005", "type": "reorder_clauses", "section": "8", "order": ["8.1", "8.3", "8.2"]},
    ],
)

section("a whole section moves as a unit")
cascade(
    "move section 11 before section 10",
    [
        {"id": "AI-006", "type": "move_section", "section": "11", "before_section": "10"},
    ],
)

section("a reference to a deleted clause is flagged, never remapped")
cascade(
    "delete section 5, which Exhibit B cites",
    [
        {"id": "AI-007", "type": "delete_section", "section": "5"},
    ],
)

section("editing a clause and then moving it")
rl, report = cascade(
    "rewrite 6.4, then move section 6",
    [
        {
            "id": "AI-008",
            "type": "rewrite_clause",
            "clause": "6.4",
            "text": "Breach Notification. Provider will notify Customer within 48 hours.",
        },
        {"id": "AI-009", "type": "move_section", "section": "6", "after_section": "2"},
    ],
)
print("    Word's move revision cannot carry the source's own strikeouts, so this")
print("    is recorded as delete + insert -- exactly as Word's own Compare does it")

section("renumber=False turns the whole thing off")
rl = fresh()
off = apply_actions(
    rl,
    [{"id": "AI-010", "type": "move_clause", "clause": "12.1", "after_clause": "4.1"}],
    renumber=False,
)
print(f"  {len(off.renumbered)} renumbered, {len(off.references)} references rewritten")
print("  the clause moves, but the document is left internally inconsistent")

section("numbering is derived as the document will read once accepted")
rl = fresh()
apply_actions(rl, [{"id": "AI-011", "type": "delete_clause", "clause": "2.3"}])
rl.accept_all()
print(
    "  after accept, section 2 reads:",
    [rl.text_of(p)[:8] for p in rl.find_paragraphs(regex=r"^2\.\d")],
)

section("the saved file keeps the cascade as tracked changes")
# The section above accepts, which is the point it is making -- but an accepted
# document has no revisions left to look at. Save the move instead, unresolved,
# so the artefact shows the cascade a reviewer would actually open.
rl = fresh()
apply_actions(
    rl, [{"id": "AI-012", "type": "move_clause", "clause": "12.1", "after_clause": "4.1"}]
)
print("  kinds:", sorted({r.kind for r in rl.summary().revisions}))

save(rl, "19_renumbering.docx")
