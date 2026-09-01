"""03 · Locating what to edit.

find_paragraphs(contains, regex, style, startswith, ignore_case, include_tables)
find_paragraph(...)      exactly one, or raises
find_text(needle, regex, ignore_case, limit)
text_of(paragraph)       the view every other method uses
"""

from _shared import banner, fresh, section

from docx_redline import RedlineError

banner("03 · Finding what to edit")
rl = fresh()

section("one filter at a time")
print("contains   :", len(rl.find_paragraphs(contains="Provider")), "paragraphs")
print("regex      :", len(rl.find_paragraphs(regex=r"^\d+\.\d+\s")), "numbered sub-clauses")
print("style      :", len(rl.find_paragraphs(style="Heading 1")), "Heading 1")
print("startswith :", len(rl.find_paragraphs(startswith="12.")), "starting '12.'")
print(
    "ignore_case:",
    len(rl.find_paragraphs(contains="PROVIDER", ignore_case=True)),
    "case-insensitive",
)
print(
    "no tables  :",
    len(rl.find_paragraphs(contains="Signature", include_tables=False)),
    "vs",
    len(rl.find_paragraphs(contains="Signature")),
    "with",
)

section("filters are ANDed")
both = rl.find_paragraphs(contains="Termination", regex=r"^4\.")
print("contains='Termination' AND regex='^4.' ->", [rl.text_of(p)[:34] for p in both])

section("find_paragraph — exactly one, or it raises")
print("ok  :", rl.text_of(rl.find_paragraph(contains="Late Payment"))[:50])
try:
    rl.find_paragraph(contains="does not appear anywhere")
except RedlineError as exc:
    print("raises:", exc)

section("find_text — character spans, not paragraphs")
for match in rl.find_text("thirty (30) days", limit=3):
    print(f"  [{match.start}:{match.end}] {match.text!r} in {rl.text_of(match.paragraph)[:38]}...")
print("regex     :", len(rl.find_text(r"\b\d+\.\d+%", regex=True)), "percentages")
print("limit=2   :", len(rl.find_text("Provider", limit=2)), "capped")

section("text_of — insertions included, deletions excluded")
para = rl.find_paragraph(contains="Late Payment")
rl.replace_text("fifteen (15) days", "thirty (30) days")
print("python-docx Paragraph.text :", para.text[-60:])
print("rl.text_of(paragraph)      :", rl.text_of(para)[-60:])
