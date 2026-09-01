"""07 · Tables.

tables()
insert_table_row(table, index=None, values=None)
delete_table_row(table, index)   delete_row(row)
set_cell_text(cell, new_text)
"""

from _shared import banner, fresh, save, section

banner("07 · Tables")
rl = fresh()

section("tables() — document order, the index update_cell uses")
for i, table in enumerate(rl.tables()):
    print(f"  table {i}: {len(table.rows)} x {len(table.columns)}")
    for r, row in enumerate(table.rows):
        print(f"     row {r}: {[c.text for c in row.cells]}")


def cells(table):
    """Cell text via rl.text_of -- python-docx's own `cell.text` cannot see runs
    inside a w:ins, so a freshly inserted row reads as empty through it."""
    return [
        [" ".join(rl.text_of(p) for p in c.paragraphs) for c in row.cells] for row in table.rows
    ]


section("insert_table_row — appended, or at an index")
rl = fresh()
table = rl.tables()[0]
rl.insert_table_row(table, values=["Countersigned by", "Date"])
rl.insert_table_row(table, index=0, values=["Party", "Detail"])
print("  via cell.text  :", [[c.text for c in r.cells] for r in rl.tables()[0].rows])
print("  via rl.text_of :", cells(rl.tables()[0]))
print("  revision kinds :", {r.kind for r in rl.summary().revisions})

section("insert_table_row with no values — an empty tracked row")
rl = fresh()
rl.insert_table_row(rl.tables()[1])
print("  rows:", len(rl.tables()[1].rows), "| kinds:", {r.kind for r in rl.summary().revisions})

section("delete_table_row(table, index) and delete_row(row)")
rl = fresh()
rl.delete_table_row(rl.tables()[0], 1)
print("  by index ->", {r.kind for r in rl.summary().revisions})
rl = fresh()
rl.delete_row(rl.tables()[1].rows[1])
print("  by row   ->", {r.kind for r in rl.summary().revisions})
print(
    "  a struck row's paragraphs drop out of rl.paragraphs():",
    len(fresh().paragraphs()),
    "->",
    len(rl.paragraphs()),
)

section("set_cell_text — word-level diff inside one cell")
rl = fresh()
cell = rl.tables()[0].rows[1].cells[0]
ops = rl.set_cell_text(cell, "Name (please print)")
print(f"  {ops} diff op(s):", [(r.kind, r.text) for r in rl.summary().revisions])

save(rl, "07_tables.docx")
