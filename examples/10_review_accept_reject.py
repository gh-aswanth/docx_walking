"""10 · Reviewing what is already there.

    summary()                    -> RevisionSummary
    accept_all() / reject_all()  -> Redliner
    accept(ids=, authors=, kinds=, where=)  -> Redliner   # and reject(...)
    accept_file(src, out, ids=...) / reject_file(src, out, ...)
    summarize(root, part=...)    the module-level form

accept/reject are not just conveniences -- they are how correctness is proved
without a copy of Word.  The filtered forms resolve a *selection* and leave
everything else as live tracked markup, which is what a partial human review
hands back.
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
print("  fields :", ["kind", "author", "date", "text", "location", "id"])
first = report.revisions[0]
print(f"  first  : id={first.id!r} kind={first.kind!r} location={first.location!r}")
print("  ids    :", report.ids[:8], "...")
print("  by_id  :", report.by_id(report.ids[0]).kind)

section("a second author stacks on top of the first")
path = save(rl, "10_first_pass.docx")
second = Redliner(path, author="In-House Counsel")
second.replace_text("forty-five (45) days", "sixty (60) days", count=1)
print("  authors now:", dict(second.summary().authors))
print("  ids never collide: the highest existing w:id is scanned on open")
both = save(second, "10_two_authors.docx")

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

section("accept(ids=...) — take one revision, leave the rest under review")
one = Redliner(both, track_changes=False)
target = next(r for r in one.summary().revisions if r.kind == "insert" and r.text)
print(f"  taking #{target.id}: {target.text[:40]!r}")
one.accept(ids=target.id)
print("  revisions left:", len(one.summary()), "of", len(Redliner(both).summary()))

section("accept/reject by author, kind, or an arbitrary predicate")
for label, call in (
    ("authors='In-House Counsel'", lambda r: r.reject(authors="In-House Counsel")),
    ("kinds='format'", lambda r: r.accept(kinds="format")),
    ("kinds='move'  (both halves, always)", lambda r: r.accept(kinds="move")),
    (
        "where=lambda rev: 'Delaware' in rev.text",
        lambda r: r.accept(where=lambda v: "Delaware" in v.text),
    ),
):
    trial = Redliner(both, track_changes=False)
    start = len(trial.summary())
    call(trial)
    print(f"  {label:<42} {start - len(trial.summary())} of {start} resolved")

section("filters are AND; values inside one filter are OR; no filter means all")
trial = Redliner(both, track_changes=False)
trial.accept(kinds=["insert", "delete"], authors="In-House Counsel")
print("  insert|delete AND by In-House Counsel ->", len(trial.summary()), "left")
print("  rl.accept() with no filter is exactly rl.accept_all()")

section("the same selection from the file helpers")
accept_file(both, OUT / "10_partial.docx", kinds="format")
print("  after accepting only formatting:", len(Redliner(OUT / "10_partial.docx").summary()))
