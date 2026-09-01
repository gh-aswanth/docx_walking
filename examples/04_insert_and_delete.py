"""04 · Inserting and deleting text.

insert_text(paragraph, offset, text)
insert_text_before(needle, text, **kw)   insert_text_after(needle, text, **kw)
append_text(paragraph, text)
delete_text(paragraph, start, end)
delete_matching(needle, regex=False, ignore_case=False, count=None)
"""

from _shared import banner, fresh, save, section

banner("04 · Insert and delete text")

section("insert_text — at a character offset")
rl = fresh()
para = rl.find_paragraph(contains="3.2  Invoicing")
rl.insert_text(para, len("3.2  Invoicing. "), "Unless the Order Form says otherwise, ")
print(rl.text_of(para)[:96], "...")

section("insert_text_before / insert_text_after — anchored on a phrase")
rl = fresh()
print("before:", rl.insert_text_before("of the invoice date", "strictly "), "insertion(s)")
print(
    "after :",
    rl.insert_text_after("of the invoice date", ", without setoff or deduction"),
    "insertion(s)",
)
print(rl.text_of(rl.find_paragraph(contains="3.2  Invoicing"))[-95:])

section("append_text — at the very end of a paragraph")
rl = fresh()
para = rl.find_paragraph(contains="12.1  Governing Law")
rl.append_text(para, " The Parties consent to exclusive jurisdiction in New York County.")
print(rl.text_of(para)[-96:])

section("delete_text — an exact character span")
rl = fresh()
para = rl.find_paragraph(contains="4.2  Auto-Renewal")
text = rl.text_of(para)
start = text.index(" automatically")
rl.delete_text(para, start, start + len(" automatically"))
print(rl.text_of(para)[:92], "...")

section("delete_matching — every hit, or the first `count`")
rl = fresh()
print("count=1     ->", rl.delete_matching("Provider shall", count=1), "deleted")
rl = fresh()
print("count=None  ->", rl.delete_matching("Provider shall"), "deleted (all)")
rl = fresh()
print(
    "regex       ->",
    rl.delete_matching(r"\s*\(d\) use the Services to build a competing product;", regex=True),
    "deleted",
)
rl = fresh()
print("ignore_case ->", rl.delete_matching("PROVIDER SHALL", ignore_case=True), "deleted")

save(rl, "04_insert_and_delete.docx")
