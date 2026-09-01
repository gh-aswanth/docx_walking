"""10 · Reviewing what is already there.

    summary()                    -> RevisionSummary
    accept_all() / reject_all()  -> Redliner
    accept_file(src, out) / reject_file(src, out)
    summarize(root, part=...)    the module-level form

accept/reject are not just conveniences -- they are how correctness is proved
without a copy of Word.
"""

from _shared import OUT, SOURCE, banner, fresh, save, section

from docx_redline import Redliner, accept_file, reject_file
from docx_redline.editing.review import summarize

banner("10 · Review, accept, reject")

section("summary() — counts by kind and author")
rl = fresh()
rl.replace_text("thirty (30) days", "forty-five (45) days", count=None)
rl.delete_paragraph(rl.find_paragraph(contains="Reservation of Rights"))
rl.move_paragraph(
    rl.find_paragraph(contains="12.1  Governing Law"),
    after=rl.find_paragraph(contains="4.1  Term."),
)
rl.format_matching("Delaware", bold=True)
print(rl.summary().format(limit=0))

section("format(limit=N) — also list the first N revisions; limit=0 for counts only")
print(rl.summary().format(limit=3))

section("counts / authors / revisions — the same thing, as data")
report = rl.summary()
print("  counts :", dict(report.counts))
print("  authors:", dict(report.authors))
print("  fields :", ["kind", "author", "date", "text", "location"])
first = report.revisions[0]
print(f"  first  : kind={first.kind!r} author={first.author!r} location={first.location!r}")

section("a second author stacks on top of the first")
path = save(rl, "10_first_pass.docx")
second = Redliner(path, author="In-House Counsel")
second.replace_text("forty-five (45) days", "sixty (60) days", count=1)
print("  authors now:", dict(second.summary().authors))
print("  ids never collide: the highest existing w:id is scanned on open")

section("summarize(root) — per part")
for part, root in (("body", rl.document.element.body),):
    print(f"  {part}: {len(summarize(root, part=part).revisions)} revisions")

section("accept_all / reject_all, in memory")
a = fresh()
a.replace_text("thirty (30) days", "forty-five (45) days")
before = a.text()
a.accept_all()
print(
    "  accept -> revisions left:",
    len(a.summary().revisions),
    "| 'forty-five' present:",
    "forty-five (45) days" in a.text(),
)

b = fresh()
b.replace_text("thirty (30) days", "forty-five (45) days")
b.reject_all()
print(
    "  reject -> revisions left:",
    len(b.summary().revisions),
    "| original restored     :",
    b.text() == Redliner(SOURCE).text(),
)

section("accept_file / reject_file — file in, file out")
accept_file(path, OUT / "10_accepted.docx")
reject_file(path, OUT / "10_rejected.docx")
print("  accepted:", len(Redliner(OUT / "10_accepted.docx").summary().revisions), "revisions")
print("  rejected:", len(Redliner(OUT / "10_rejected.docx").summary().revisions), "revisions")
print(
    "  reject(redlined) == original:",
    Redliner(OUT / "10_rejected.docx").text() == Redliner(SOURCE).text(),
)
