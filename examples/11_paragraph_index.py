"""11 · ParagraphIndex — the stable integer address space.

    ParagraphIndex(rl, include_tables=True)
      len / iter / index[pid]      -> ParagraphRef
      .clauses .paragraph(pid) .find(needle, ignore_case)
      .render(para_ids, with_clause_labels, skip_empty)
      .manifest() .fingerprint() .locate(...) .apply(...) .refresh()

Clause numbers are the right address for a lawyer and the wrong one for a
machine. Ids are positions in rl.paragraphs() and survive every text edit.
"""

from _shared import banner, fresh, section

from docx_redline import ParagraphIndex, RedlineEdit

banner("11 · ParagraphIndex")
rl = fresh()
index = ParagraphIndex(rl)

section("the index itself")
print(f"  {len(index)} paragraphs, {len(index.clauses)} numbered clauses")
print(f"  fingerprint: {index.fingerprint()}")

section("ParagraphRef — every field")
ref = index[19]
for field in (
    "para_id",
    "text",
    "style",
    "numbered",
    "in_table",
    "table_index",
    "clause_label",
    "level",
    "is_empty",
):
    value = getattr(ref, field)
    print(
        f"  {field:<13} = {str(value)[:58]!r}" if field == "text" else f"  {field:<13} = {value!r}"
    )

section("a paragraph inside a table")
tabled = next(r for r in index if r.in_table)
print(
    f"  [{tabled.para_id}] in_table={tabled.in_table} table_index={tabled.table_index} "
    f"text={tabled.text!r}"
)

section("include_tables=False — table cells drop out of the address space")
print("  with tables   :", len(ParagraphIndex(fresh())))
print("  without tables:", len(ParagraphIndex(fresh(), include_tables=False)))

section("find(needle, ignore_case) — folded on both sides")
print("  'thirty (30) days'        ->", index.find("thirty (30) days"))
print(
    "  '(\"Agreement\")' straight  ->",
    index.find('("Agreement")'),
    "   <- the document has curly quotes",
)
print("  'PROVIDER' ignore_case    ->", index.find("PROVIDER", ignore_case=True)[:6], "...")

section("paragraph(pid) — the live python-docx object")
print("  ", type(index.paragraph(19)).__name__, "|", rl.text_of(index.paragraph(19))[:52])

section("render() — the cacheable prefix a model reads")
print(index.render(para_ids=range(17, 21)))

section("render options")
print("  with_clause_labels=False:")
print("   ", index.render(para_ids=range(18, 20), with_clause_labels=False).replace("\n", "\n    "))
print(f"  skip_empty=True  -> {len(index.render().splitlines())} lines")
print(f"  skip_empty=False -> {len(index.render(skip_empty=False).splitlines())} lines")

section("manifest() — routing input, one line per clause")
print("\n".join("  " + line for line in index.manifest().splitlines()[:6]))

section("locate() — resolve a quote without applying anything")
print("  hit      :", index.locate(19, "thirty (30) days"))
print("  every hit:", index.locate(6, "Provider", occurrence=0))
print("  refusal  :", index.locate(19, "not in this paragraph"))

section("refresh() — re-index after structural work")
index.apply([RedlineEdit(19, "thirty (30) days", "forty-five (45) days")])
print("  ids survive a text edit:", index[19].text[-46:])
rl.insert_paragraph_after(rl.find_paragraph(contains="3.4  Taxes"), "3.5  Currency.")
print("  after inserting a paragraph, len(index) is stale:", len(index))
index.refresh()
print("  refresh() ->", len(index), "paragraphs, new fingerprint", index.fingerprint())
