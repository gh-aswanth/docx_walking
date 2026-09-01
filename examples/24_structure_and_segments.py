"""24 · Reading the document's structure.

    ClauseTree(body)   Clause   parse_clause(p)   iter_references(text)
    outline(tree, body_chars=240)   render_outline(tree, body_chars=400, clauses=None)
    detect_strategy(body, tree=None)
    iter_blocks(body, tree=None)
    render_document(body, tree=None)
    segment_document(body, budget_tokens=25_000, strategy="auto", tree=None)

Read-only: nothing here writes a revision.
"""

import docx
from _shared import SOURCE, banner, section

from docx_redline import (
    ClauseTree,
    detect_strategy,
    iter_blocks,
    iter_references,
    outline,
    render_document,
    render_outline,
    segment_document,
)

banner("24 · Structure and segments")
body = docx.Document(SOURCE).element.body
tree = ClauseTree(body)

section("ClauseTree — nested by level, in body order")
print(f"  {len(tree.all())} clauses in {len(tree.sections)} sections")
for section_clause in tree.sections[:3]:
    print(f"  {section_clause.label:<5} {section_clause.title}")
    for child in section_clause.children:
        print(f"    {child.label:<6} {child.title or child.body[:44]}")

section("Clause — every field")
clause = tree.get("3.2")
for field in ("label", "number", "span", "title", "level", "inserted", "moved"):
    print(f"  {field:<9} = {getattr(clause, field)!r}")
print(f"  {'text':<9} = {clause.text[:56]!r}")
print(f"  {'body':<9} = {clause.body[:56]!r}   <- number stripped")
print(f"  {'parent':<9} = {clause.parent.label if clause.parent else None!r}")
print(f"  {'children':<9} = {[c.label for c in clause.children]}")

section("lookup and traversal")
print("  tree.get('10.2') ->", tree.get("10.2").title)
print("  walk from 10    ->", [c.label for c in tree.get("10").walk()])
print("  duplicates      ->", tree.duplicates or "none")

section("outline / render_outline — the summary view")
rows = outline(tree, body_chars=60)
print("  outline() gives dicts:", list(rows[0]))
print("  render_outline(body_chars=50):")
print("\n".join("    " + line for line in render_outline(tree, body_chars=50).splitlines()[:6]))
print("  ...but it truncates, which is why the reviewer gets render_document instead")

section("iter_references — every cross-reference in a piece of text")
text = tree.get("10.3").text if tree.get("10.3") else ""
for start, end, kind, number in iter_references(
    "The limitations in Section 10.2 shall not apply, and Sections 4.1 and 4.2 survive."
):
    print(f"  [{start}:{end}] {kind} {number}")

section("detect_strategy — which structural signal this file carries")
print(
    "  ",
    detect_strategy(body),
    " (clause numbers > outlineLvl > Heading styles > numPr > typography > windows)",
)

section("iter_blocks — every paragraph and table, in reading order")
blocks = iter_blocks(body, tree)
print(
    f"  {len(blocks)} blocks: "
    f"{sum(1 for b in blocks if b.kind == 'para')} paragraphs, "
    f"{sum(1 for b in blocks if b.kind == 'table')} tables"
)
for block in blocks[6:10]:
    print(
        f"    {block.ordinal:>3} {block.kind:<6} level={block.level} "
        f"{(block.clause.label if block.clause else '-'):<6} {block.text[:44]}"
    )
table = next(b for b in blocks if b.kind == "table")
print(
    f"    {table.ordinal:>3} {table.kind:<6} table_index={table.table_index} "
    f"{table.text.splitlines()[0]}"
)

section("render_document — the whole thing, untruncated")
rendered = render_document(body, tree)
print(f"  {len(rendered.splitlines())} lines, {len(rendered)} chars")
print("  includes the exhibits a clause-only view drops:")
for line in rendered.splitlines():
    if line.strip().startswith("Exhibit"):
        print("    ", line.strip()[:64])

section("segment_document — request-sized pieces, cut on structure")
for budget in (25_000, 1_500, 800):
    segments = segment_document(body, budget_tokens=budget)
    print(
        f"  budget={budget:<6} -> {len(segments)} segment(s): {[s.approx_tokens for s in segments]}"
    )

section("DocSegment — every field")
seg = segment_document(body, budget_tokens=800)[1]
for field in ("id", "index", "strategy", "title", "chars", "approx_tokens"):
    print(f"  {field:<14} = {getattr(seg, field)!r}")
print(f"  {'labels':<14} = {sorted(seg.labels)[:8]} ...")
print(f"  {'tables':<14} = {seg.tables}")
print(f"  {'blocks':<14} = {len(seg.blocks)}")

section("strategy= — force a segmentation signal")
for strategy in ("auto", "clauses", "headings", "windows"):
    segments = segment_document(body, budget_tokens=800, strategy=strategy)
    print(
        f"  strategy={strategy:<9} -> {len(segments)} segment(s), "
        f"reported as {segments[0].strategy!r}"
    )

section("split() — halve a segment at a structural boundary")
seg = segment_document(body, budget_tokens=25_000)[0]
halves = seg.split()
print(
    "  ",
    f"{seg.approx_tokens} tok -> {[h.approx_tokens for h in halves] if halves else 'indivisible'}",
)
print("  used when a model truncates: the fix is a smaller span, but only if")
print("  there is somewhere safe to cut")
