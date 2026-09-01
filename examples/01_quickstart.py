"""01 · Quickstart — the smallest useful redline.

Four edits, one save. Everything else in this folder is a variation on this.
"""

from _shared import OUT, SOURCE, banner, section

from docx_redline import Redliner

banner("01 · Quickstart")

rl = Redliner(SOURCE, author="Outside Counsel")

rl.replace_text("thirty (30) days", "forty-five (45) days")
rl.insert_text_after("of the invoice date", ", without setoff or deduction")

clause = rl.find_paragraph(contains="Late Payment")
rl.set_paragraph_text(clause, rl.text_of(clause).replace("fifteen (15) days", "thirty (30) days"))
rl.delete_paragraph(rl.find_paragraph(contains="Reservation of Rights"))

section("what changed")
print(rl.summary().format(limit=10))

rl.save(OUT / "01_quickstart.docx")
print(f"\nwrote {OUT.name}/01_quickstart.docx  -- open in Word > Review > All Markup")
