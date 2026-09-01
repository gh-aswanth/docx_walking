"""12 · RedlineEdit and ReviewNote — every field.

    RedlineEdit(para_id, target, replacement="", rationale="", agent="",
                severity="medium", occurrence=1, insertion_first=False)
    ReviewNote(para_id, target, body, agent="", severity="medium", occurrence=1)

`target` is an exact quoted span, never an offset. Offsets do not survive a
reparse; a quote does, and a quote that no longer matches is a signal the
document moved on rather than a bug to route around.
"""

from _shared import banner, fresh, save, section

from docx_redline import ParagraphIndex, RedlineEdit, ReviewNote

banner("12 · Edits and notes")

section("a replacement, a deletion, and every metadata field")
rl = fresh()
index = ParagraphIndex(rl)
report = index.apply(
    [
        RedlineEdit(
            19,
            "thirty (30) days",
            "forty-five (45) days",
            rationale="Net 45 matches our AP cycle.",
            agent="payment-terms",
            severity="high",
        ),
        # replacement="" is a pure deletion
        RedlineEdit(19, " of the invoice date", "", agent="payment-terms", severity="low"),
    ]
)
print(report.summary())
print("  p19 now:", index[19].text[-60:])

section("occurrence — 1-based, or 0 for every hit")
for occ in (1, 2, 0):
    rl = fresh()
    index = ParagraphIndex(rl)
    r = index.apply([RedlineEdit(6, "Provider", "Vendor", occurrence=occ)])
    got = r.applied[0].spans if r.applied else r.rejected[0].reason.value
    print(f"  occurrence={occ} -> {got} span(s)")
    if r.applied:
        text = index[6].text
        print(f"     ...{text[max(0, text.find('Vendor') - 40) :][:88]}")

section("insertion_first — which half the reviewer sees first")
for flag in (False, True):
    rl = fresh()
    index = ParagraphIndex(rl)
    index.apply([RedlineEdit(19, "thirty (30) days", "forty-five (45) days", insertion_first=flag)])
    print(f"  insertion_first={flag!s:<5} -> {[r.kind for r in rl.summary().revisions]}")

section("ReviewNote — anchored to the span, signed by its agent")
rl = fresh()
index = ParagraphIndex(rl)
index.apply(
    [
        ReviewNote(
            19,
            "annually in advance",
            "Confirm AP can fund an annual prepay.",
            agent="Payment Terms",
            severity="medium",
        ),
        ReviewNote(
            49,
            "TWELVE (12) MONTHS",
            "Cap is below one year of fees at list price.",
            agent="Risk",
            severity="high",
        ),
    ]
)
for c in rl.document.comments:
    print(f"  [{c.author}/{c.initials}] {c.text}")
body = rl.document.element.body.xml
print(
    "  anchored on the phrase:",
    body.index("commentRangeStart")
    < body.index("annually in advance")
    < body.index("commentRangeEnd"),
)

section("a note and an edit may share a span — notes never claim")
rl = fresh()
index = ParagraphIndex(rl)
report = index.apply(
    [
        ReviewNote(19, "thirty (30) days", "Too short for our AP cycle."),
        RedlineEdit(19, "thirty (30) days", "forty-five (45) days"),
    ]
)
print(f"  {len(report.applied)} applied, {len(report.rejected)} rejected")

section("notes are re-located against the finished text")
rl = fresh()
index = ParagraphIndex(rl)
report = index.apply(
    [
        RedlineEdit(19, "thirty (30) days", "forty-five (45) days"),
        ReviewNote(19, "thirty (30) days", "Superseded by the Net 45 edit."),
    ]
)
print("  note detail:", report.applied[1].detail)
print("  an edit struck the words the note quotes, so it falls back to the")
print("  paragraph and says so -- rather than pointing at a stale offset")

section("EditResult / ApplyReport")
print("  applied :", len(report.applied), " rejected:", len(report.rejected))
result = report.applied[0]
print(f"  result  : applied={result.applied} spans={result.spans} reason={result.reason}")
print("  to_dict :", list(report.to_dict()))

save(rl, "12_edits_and_notes.docx")
