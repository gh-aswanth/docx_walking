"""14 · fold() — matching what Word actually stored.

Every mapping is exactly one character to one character. That is what makes an
offset computed on the folded string valid on the raw string it came from, and
it is the whole reason offsets can be handed straight to the edit primitives.
"""

import unicodedata

from _shared import banner, fresh, section

from docx_redline import ParagraphIndex, RedlineEdit, fold

banner("14 · fold()")

section("what it folds")
for label, raw in [
    ("smart quotes  ", "“Agreement” and Customer’s"),
    ("dashes        ", "twelve–12—month − rule"),
    ("prime marks   ", "6′ by 4″"),
    ("nbsp / thin sp", "30 days apart"),
    ("zero width    ", "Order​Form﻿"),
    ("tab           ", "Fees\tpayable"),
    ("fullwidth     ", "ＡＢＣ"),
]:
    print(f"  {label} {raw!r}\n{'':17} -> {fold(raw)!r}")

section("length is preserved, always — that is the invariant")
for raw in [
    "“twelve (12)–month” term",
    "a non-breaking space",
    "an apostrophe’s curl",
    "Ａ fullwidth",
    "a\ttab",
]:
    print(
        f"  len {len(raw):>3} -> {len(fold(raw)):>3}  "
        f"{'ok' if len(fold(raw)) == len(raw) else 'BROKEN'}"
    )

section("ligatures are left alone on purpose")
print(
    f"  NFKC('ofﬁce')  = {unicodedata.normalize('NFKC', 'ofﬁce')!r}  (len "
    f"{len(unicodedata.normalize('NFKC', 'ofﬁce'))}) -- would shift every later offset"
)
print(f"  fold('ofﬁce')  = {fold('ofﬁce')!r}  (len {len(fold('ofﬁce'))}) -- left as-is")
print("  NFKC is applied one character at a time and kept only when it maps 1 -> 1")

section("why it matters: a model quotes straight, Word stored curly")
rl = fresh()
index = ParagraphIndex(rl)
print("  document has:", index[3].text[index[3].text.index("(") : index[3].text.index(")") + 1])
report = index.apply([RedlineEdit(3, '("Agreement")', '("Master Agreement")', agent="definitions")])
print(" ", report.summary().splitlines()[0])
print("  result:", index[3].text[60:130])

section("find() and locate() fold both sides too")
print("  find('(\"Agreement\")')      ->", index.find('("Agreement")') or "no hit (already edited)")
print("  find('Customer\\'s') straight ->", ParagraphIndex(fresh()).find("Customer's")[:5], "...")

section("it does not fold case — that is what ignore_case is for")
print("  fold('PROVIDER') ==", repr(fold("PROVIDER")))
print(
    "  find('PROVIDER')            ->",
    ParagraphIndex(fresh()).find("PROVIDER"),
    "<- only 9.3, which really is in caps",
)
print(
    "  find('PROVIDER', ignore_case=True) ->",
    ParagraphIndex(fresh()).find("PROVIDER", ignore_case=True)[:5],
    "...",
)
