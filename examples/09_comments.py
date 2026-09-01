"""09 · Comments.

    add_comment(paragraph, text, runs=None, author=None, initials=None)

Requires python-docx >= 1.2. A comment is not a tracked change: it carries no
Accept/Reject, and `summary()` does not count it.
"""

from _shared import banner, fresh, save, section

from docx_redline.oxml.textmap import split_range

banner("09 · Comments")

section("the whole paragraph")
rl = fresh()
rl.add_comment(
    rl.find_paragraph(contains="10.2  Liability Cap"),
    "Confirm the cap multiple with finance before signature.",
)
for c in rl.document.comments:
    print(f"  [{c.author}/{c.initials}] {c.text}")

section("author / initials — sign each note with the agent that raised it")
rl = fresh()
rl.add_comment(
    rl.find_paragraph(contains="6.3  Security"),
    "Ask whether ISO 27001 is in scope.",
    author="Security Review",
)
rl.add_comment(
    rl.find_paragraph(contains="10.2  Liability Cap"),
    "Cap is below one year of fees.",
    author="Risk",
    initials="RSK",
)
for c in rl.document.comments:
    print(f"  [{c.author}/{c.initials}] {c.text}")
print("  initials are derived from the name unless given")

section("runs= — anchor on a phrase instead of the paragraph")
rl = fresh()
para = rl.find_paragraph(contains="3.2  Invoicing")
text = rl.text_of(para)
start = text.index("annually in advance")
end = start + len("annually in advance")
view = split_range(para._p, start, end)  # force run boundaries
runs = list(view.runs_in(start, end))
from docx.text.run import Run

rl.add_comment(
    para,
    "Confirm AP can fund an annual prepay.",
    runs=[Run(r, para) for r in runs],
    author="Payment Terms",
)
body = rl.document.element.body.xml
print(
    "  range opens before the phrase:",
    body.index("commentRangeStart") < body.index("annually in advance"),
)
print(
    "  and closes after it          :",
    body.index("annually in advance") < body.index("commentRangeEnd"),
)
print("  (ParagraphIndex + ReviewNote does this for you -- see 12_edits_and_notes.py)")

section("commenting on a strikeout")
rl = fresh()
para = rl.find_paragraph(contains="2.3  Reservation of Rights")
rl.delete_paragraph(para)
rl.add_comment(para, "Struck: redundant with the licence grant in 2.1.", author="IP")
print("  a struck paragraph has no visible runs, so the comment falls back to")
print("  its deleted runs -- which is exactly where a reviewer wants to see it")

section("comments are not tracked changes")
print(
    "  summary() counts:",
    len(rl.summary().revisions),
    "revisions,",
    sum(1 for _ in rl.document.comments),
    "comment(s) alongside",
)

save(rl, "09_comments.docx")
