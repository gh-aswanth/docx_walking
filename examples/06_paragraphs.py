"""06 · Whole paragraphs: insert, delete, move.

insert_paragraph_before/after(reference, text="", style=None, copy_format=True)
append_paragraph(text, style=None)
delete_paragraph(paragraph)   delete_paragraphs(paragraphs)
move_paragraph(paragraph, after)
relocate_paragraph(source, after=None, before=None)
apply_style(paragraph, name)
"""

from _shared import banner, fresh, save, section

banner("06 · Paragraphs")

section("insert_paragraph_after / _before")
rl = fresh()
anchor = rl.find_paragraph(contains="3.4  Taxes")
rl.insert_paragraph_after(anchor, "3.5  Currency. All amounts are payable in U.S. dollars.")
rl.insert_paragraph_before(anchor, "3.3a  Disputed Amounts. Customer may withhold disputed sums.")
for rev in rl.summary().revisions:
    print(f"   [{rev.kind}] {rev.text[:62]}")

section("copy_format — inherit the reference paragraph's look, or start clean")
for flag in (True, False):
    rl = fresh()
    new = rl.insert_paragraph_after(
        rl.find_paragraph(contains="3.4  Taxes"), "3.5  Currency.", copy_format=flag
    )
    pPr = new._p.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pPr")
    kids = [c.tag.split("}")[-1] for c in pPr] if pPr is not None else []
    print(f"copy_format={flag!s:<5} -> pPr children: {kids}")

section("style — by name, at insert time or afterwards")
rl = fresh()
rl.insert_paragraph_after(
    rl.find_paragraph(contains="3.4  Taxes"), "3.5  Currency.", style="Heading 2"
)
rl.apply_style(rl.find_paragraph(contains="1.1  “Authorized Users”"), "Heading 4")
print("styles available:", ", ".join(rl.paragraph_style_names()[:6]), "...")

section("append_paragraph — at the very end of the body")
rl = fresh()
rl.append_paragraph("Signed on behalf of the Parties by their authorised representatives.")
print("   last revision:", rl.summary().revisions[-1].text[:66])

section("delete_paragraph / delete_paragraphs")
rl = fresh()
rl.delete_paragraph(rl.find_paragraph(contains="2.3  Reservation of Rights"))
print("one     ->", len(rl.summary().revisions), "revisions (text + the ¶ mark)")
rl = fresh()
n = rl.delete_paragraphs(rl.find_paragraphs(regex=r"^5\.\d"))
print(f"many    -> {n} paragraphs struck")

section("move_paragraph — a real w:moveFrom / w:moveTo pair")
rl = fresh()
rl.move_paragraph(
    rl.find_paragraph(contains="12.1  Governing Law"),
    after=rl.find_paragraph(contains="4.1  Term."),
)
print(" ", {r.kind for r in rl.summary().revisions})
print("  Word labels these 'Moved from' / 'Moved to'")

section("relocate_paragraph — the element-level form, before= or after=")
rl = fresh()
rl.relocate_paragraph(
    rl.find_paragraph(contains="7.2  Customer Data")._p,
    before=rl.find_paragraph(contains="7.1  Provider IP")._p,
)
print(" ", {r.kind for r in rl.summary().revisions})

save(rl, "06_paragraphs.docx")
