"""23 · Comparing two documents — Word's Compare, in Python.

    redline_files(original, revised, output, **kwargs) -> CompareStats
    compare_documents(original, revised, author="Compare", date=None,
                      track_changes=True, similarity_floor=0.45)
        -> (Redliner, CompareStats)

The redline is built on top of the *original*, so its styles, numbering,
headers and section setup are preserved; paragraphs that only exist in the
revised file are grafted in with their own formatting.
"""

from _shared import OUT, SOURCE, banner, section

from docx_redline import Redliner, compare_documents, redline_files

banner("23 · Document compare")

section("build a 'counterparty markup' to compare against")
revised = OUT / "23_counterparty.docx"
cp = Redliner(SOURCE, author="Counterparty", track_changes=False)
cp.replace_text("thirty (30) days", "sixty (60) days", count=None)
cp.replace_text("seventy-two (72) hours", "five (5) business days")
cp.delete_paragraph(cp.find_paragraph(contains="2.3  Reservation of Rights"))
cp.insert_paragraph_after(
    cp.find_paragraph(contains="3.4  Taxes"), "3.5  Currency. Amounts are payable in EUR."
)
cp.accept_all()
cp.save(revised)
print(f"  wrote {revised.name} with four changes baked in (no tracked changes)")

section("redline_files — file in, file out")
stats = redline_files(SOURCE, revised, OUT / "23_compare.docx", author="Compare Bot")
print(stats.format())

section("compare_documents — when you want the Redliner back")
rl, stats = compare_documents(SOURCE, revised, author="Compare Bot")
print("  kinds:", dict(rl.summary().counts))
print("  the result is a live Redliner, so you can keep editing:")
rl.add_comment(
    rl.find_paragraph(contains="3.2  Invoicing"),
    "Counterparty pushed Net 60 - we asked for 45.",
    author="Deal Team",
)
print("  ", sum(1 for _ in rl.document.comments), "comment added on top of the diff")
rl.save(OUT / "23_compare_annotated.docx")

section("similarity_floor — when is a pair a rewrite, not a diff?")
for floor in (0.20, 0.45, 0.95):
    _, s = compare_documents(SOURCE, revised, similarity_floor=floor)
    print(f"  similarity_floor={floor:<5} -> {s.format().splitlines()[0]}")
print("  below the floor a paragraph pair is emitted as delete + insert rather")
print("  than an unreadable word-by-word diff of two unrelated sentences")

section("author / date / track_changes flow through")
rl, _ = compare_documents(
    SOURCE, revised, author="Nightly Diff", date="2026-01-01T00:00:00Z", track_changes=False
)
print("  authors:", dict(rl.summary().authors))
print("  date   :", rl.ctx.author.date)

section("the comparison is provably correct")
rl, _ = compare_documents(SOURCE, revised)
accepted = Redliner(OUT / "23_compare.docx")
accepted.accept_all()
rejected = Redliner(OUT / "23_compare.docx")
rejected.reject_all()
print("  accept(compare) == revised :", accepted.text() == Redliner(revised).text())
print("  reject(compare) == original:", rejected.text() == Redliner(SOURCE).text())

section("CompareStats")
print("  fields:", list(vars(stats)))
print("  ", stats.format())
