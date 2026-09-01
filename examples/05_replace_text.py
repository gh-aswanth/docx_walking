"""05 · Replacing text — every option.

replace_text(old, new, regex=False, ignore_case=False,
             count=1, insertion_first=False)
set_paragraph_text(paragraph, new_text, ignore_case=False)
"""

from _shared import banner, fresh, save, section

banner("05 · Replace text")

section("count — 1 (default), a number, or None for every occurrence")
for count in (1, 3, None):
    rl = fresh()
    n = rl.replace_text("thirty (30) days", "forty-five (45) days", count=count)
    print(f"count={count!s:<5} -> {n} replacement(s)")

section("regex with backreferences — `new` is expanded against the match")
rl = fresh()
n = rl.replace_text(r"(\d+)\.(\d)% per month", r"\1.0% per month", regex=True)
print(f"1.5% per month -> 1.0% per month  ({n} replacement)")
print(rl.text_of(rl.find_paragraph(contains="Late Payment"))[:96], "...")

section("ignore_case")
rl = fresh()
print(
    "matched:",
    rl.replace_text(
        "PROVIDER SHALL INVOICE", "Provider will invoice", ignore_case=True, count=None
    ),
    "occurrence(s)",
)

section("insertion_first — which half the reviewer sees first")
for flag in (False, True):
    rl = fresh()
    rl.replace_text("thirty (30) days", "forty-five (45) days", insertion_first=flag)
    order = [r.kind for r in rl.summary().revisions]
    print(f"insertion_first={flag!s:<5} -> {order}   (Word's own Compare uses False)")

section("replace across run boundaries — one revision, three fonts")
rl = fresh()
para = rl.find_paragraph(contains="9.3  Disclaimer")
print("runs before:", len(para.runs))
rl.replace_text("AS IS", "AS PROVIDED", count=1)
print("still one clean revision:", [r.kind for r in rl.summary().revisions])

section("set_paragraph_text — word-level diff, marks only what moved")
rl = fresh()
para = rl.find_paragraph(contains="4.3  Termination for Cause")
ops = rl.set_paragraph_text(
    para,
    rl.text_of(para)
    .replace("thirty (30) days", "fifteen (15) days")
    .replace("materially breaches", "commits a material breach of"),
)
print(f"{ops} diff op(s) instead of striking the whole clause")
for rev in rl.summary().revisions:
    print(f"   [{rev.kind}] {rev.text[:44]}")

save(rl, "05_replace_text.docx")
