"""08 · Formatting revisions — w:rPrChange and w:pPrChange.

    format_runs(runs, **props)
    format_matching(needle, regex=False, count=None, **props)
    format_paragraph_text(paragraph, **props)
    format_paragraph(paragraph, **props)

Accepting keeps the new formatting; rejecting restores the old, because the
pre-edit properties are stored in the *PrChange baseline.
"""

from _shared import banner, fresh, save, section
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

banner("08 · Formatting")

section("run properties — every accepted key")
rl = fresh()
props = {
    "bold": True,
    "italic": True,
    "underline": True,
    "strike": False,
    "name": "Georgia",
    "size": Pt(11),
    "color": "C00000",
    "highlight": "YELLOW",
    "subscript": False,
    "superscript": False,
}
for key, value in props.items():
    n = rl.format_matching("Confidential Information", count=1, **{key: value})
    print(f"  {key:<12} = {value!s:<22} -> {n} run(s)")

section("format_matching — count and regex")
rl = fresh()
print("  count=1    ->", rl.format_matching("Provider", count=1, bold=True), "run(s)")
rl = fresh()
print("  count=None ->", rl.format_matching("Provider", bold=True), "run(s) (all)")
rl = fresh()
print("  regex      ->", rl.format_matching(r"\d+\.\d+%", regex=True, color="C00000"), "run(s)")

section("format_runs — when you already hold the runs")
rl = fresh()
para = rl.find_paragraph(contains="9.3  Disclaimer")
print("  ", rl.format_runs(para.runs, bold=True, highlight="YELLOW"), "run(s) reformatted")

section("format_paragraph_text — every run in one paragraph")
rl = fresh()
print(
    "  ",
    rl.format_paragraph_text(rl.find_paragraph(contains="10.2  Liability Cap"), italic=True),
    "run(s)",
)

section("paragraph properties — w:pPrChange")
rl = fresh()
para = rl.find_paragraph(contains="6.4  Breach Notification")
rl.format_paragraph(
    para,
    alignment=WD_ALIGN_PARAGRAPH.JUSTIFY,
    space_before=Pt(12),
    space_after=Pt(18),
    left_indent=Pt(18),
    right_indent=Pt(6),
    first_line_indent=Pt(12),
    line_spacing=1.15,
    keep_together=True,
    keep_with_next=False,
    page_break_before=False,
)
print("  kinds:", {r.kind for r in rl.summary().revisions})

section("style: format_paragraph tracks it, apply_style does not")
rl = fresh()
rl.format_paragraph(rl.find_paragraph(contains="1.1  “Authorized Users”"), style="Heading 4")
print("  format_paragraph(style=) ->", {r.kind for r in rl.summary().revisions} or "no revision")

rl = fresh()
para = rl.find_paragraph(contains="1.1  “Authorized Users”")
rl.apply_style(para, "Heading 4")
print(
    "  apply_style(...)         ->",
    {r.kind for r in rl.summary().revisions} or "no revision",
    f"(style is now {para.style.name!r})",
)
print("  apply_style is the untracked escape hatch: it also resolves a style whose")
print("  w:name casing python-docx refuses to map. Use format_paragraph to record it.")

section("reject restores the baseline")
rl = fresh()
para = rl.find_paragraph(contains="12.1  Governing Law")
rl.format_matching("Delaware", bold=True, color="C00000")
print("  before reject:", len(rl.summary().revisions), "revision(s)")
rl.reject_all()
print("  after  reject:", len(rl.summary().revisions), "revision(s)")

rl = fresh()
rl.format_matching("Delaware", bold=True, color="C00000")
rl.format_paragraph(rl.find_paragraph(contains="6.4  Breach"), alignment=WD_ALIGN_PARAGRAPH.JUSTIFY)
save(rl, "08_formatting.docx")
