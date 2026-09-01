"""13 · Every rejection, one at a time.

Nothing is written until every item has been located, so a plan that is half
wrong cannot leave the document half edited by the time it is found out.

    PARAGRAPH_NOT_FOUND    para_id out of range
    EMPTY_TARGET           target is empty or whitespace only
    TARGET_NOT_FOUND       the quote does not match -- never fuzzy-matched
    TARGET_AMBIGUOUS       repeated, and under 25 characters
    TARGET_ALREADY_STRUCK  the text exists only inside an existing w:del
    SPAN_CONFLICT          an earlier edit in the batch claimed those characters
"""

from _shared import banner, fresh, section

from docx_redline import ParagraphIndex, RedlineEdit, Rejection, ReviewNote

banner("13 · Rejections")


def attempt(title, items, prepare=None):
    rl = fresh()
    index = ParagraphIndex(rl)
    if prepare:
        prepare(index)
    report = index.apply(items)
    print(f"\n  {title}")
    for res in report.results:
        mark = "APPLIED " if res.applied else "REJECTED"
        why = "" if res.applied else f"  <- {res.reason.value}"
        print(f"    {mark} p{res.item.para_id}: {res.item.target[:38]!r}{why}")
        if not res.applied:
            print(f"      {res.detail}")
    return report, rl


section("one paragraph, one reason each")

attempt(
    "PARAGRAPH_NOT_FOUND — the detail names the valid range", [RedlineEdit(9999, "anything", "x")]
)

attempt("EMPTY_TARGET", [RedlineEdit(19, "   ", "x")])

attempt(
    "TARGET_NOT_FOUND — a plausible paraphrase is still not the text",
    [RedlineEdit(19, "net thirty (30) days from receipt", "net forty-five (45) days")],
)

attempt(
    "TARGET_AMBIGUOUS — 'Provider' twice in the preamble, under 25 chars",
    [RedlineEdit(6, "Provider", "Vendor")],
)

attempt(
    "TARGET_ALREADY_STRUCK — for an edit",
    [RedlineEdit(19, "thirty (30) days", "sixty (60) days")],
    prepare=lambda ix: ix.apply([RedlineEdit(19, "thirty (30) days", "forty-five (45) days")]),
)

attempt(
    "TARGET_ALREADY_STRUCK — for a note it is a fallback, not a refusal",
    [ReviewNote(19, "thirty (30) days", "Superseded; kept for the audit trail.")],
    prepare=lambda ix: ix.apply([RedlineEdit(19, "thirty (30) days", "forty-five (45) days")]),
)

attempt(
    "SPAN_CONFLICT — two agents rewriting one span",
    [
        RedlineEdit(19, "thirty (30) days", "forty-five (45) days", agent="payment-terms"),
        RedlineEdit(19, "thirty (30) days", "ten (10) days", agent="rogue-agent"),
    ],
)

attempt(
    "...but disjoint edits in one paragraph both land",
    [
        RedlineEdit(19, "thirty (30) days", "forty-five (45) days"),
        RedlineEdit(19, "of the invoice date", "of receipt of a valid invoice"),
    ],
)

section("nothing is written when an item is rejected")
rl = fresh()
index = ParagraphIndex(rl)
index.apply([RedlineEdit(19, "no such phrase", "x")])
print("  revisions in the document:", len(rl.summary().revisions))

section("resolving an ambiguity, three ways")
for label, edit in [
    ("occurrence=2", RedlineEdit(6, "Provider", "Vendor", occurrence=2)),
    ("occurrence=0", RedlineEdit(6, "Provider", "Vendor", occurrence=0)),
    (
        "quote more  ",
        RedlineEdit(
            6, "use of Provider’s cloud-based software platform", "use of the Vendor platform"
        ),
    ),
]:
    report = ParagraphIndex(fresh()).apply([edit])
    ok = report.applied[0].spans if report.applied else report.rejected[0].reason.value
    print(f"  {label} -> {ok}")

section("the enum, for programmatic handling")
print("  ", [r.name for r in Rejection])
report = ParagraphIndex(fresh()).apply([RedlineEdit(6, "Provider", "Vendor")])
if report.rejected[0].reason is Rejection.TARGET_AMBIGUOUS:
    print("   caught Rejection.TARGET_AMBIGUOUS -> route to a human, or retry with occurrence")
