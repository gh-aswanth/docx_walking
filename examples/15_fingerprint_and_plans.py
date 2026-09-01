"""15 · fingerprint / verify_plan — refusing a stale plan.

    fingerprint(source)                 a ParagraphIndex, a Redliner, or a path
    verify_plan(source, plan_fingerprint)  -> the current fingerprint, or raises

This is the guard that stops a v3 redline landing on a v4 document.
"""

from _shared import OUT, SOURCE, banner, fresh, section

from docx_redline import (
    ParagraphIndex,
    RedlineEdit,
    Redliner,
    StalePlanError,
    fingerprint,
    verify_plan,
)

banner("15 · Fingerprints and stale plans")

section("fingerprint accepts three things")
rl = fresh()
index = ParagraphIndex(rl)
print("  a ParagraphIndex:", fingerprint(index))
print("  a Redliner      :", fingerprint(fresh()))
print("  a path          :", fingerprint(SOURCE))
print("  all identical   :", fingerprint(index) == fingerprint(fresh()) == fingerprint(SOURCE))

section("it hashes text only — attribution and dates do not disturb it")
a = fingerprint(Redliner(SOURCE, author="Alice", date="2020-01-01T00:00:00Z"))
b = fingerprint(Redliner(SOURCE, author="Bjorn", date="2026-09-01T00:00:00Z"))
print(f"  Alice/2020 = {a}\n  Bjorn/2026 = {b}\n  equal      = {a == b}")

section("the normal flow: capture, hand out, verify, apply")
plan_fp = index.fingerprint()
print("  1. capture   ", plan_fp)
print("  2. ...the model thinks about it for a while...")
print("  3. verify    ", verify_plan(index, plan_fp), "<- returns the current fingerprint")
index.apply([RedlineEdit(19, "thirty (30) days", "forty-five (45) days")])
print("  4. applied. document is now", index.fingerprint())

section("re-verifying the same plan now refuses")
try:
    verify_plan(index, plan_fp)
except StalePlanError as exc:
    print("  StalePlanError:", exc)

section("catching it is the point — re-plan, do not force")
rl = fresh()
index = ParagraphIndex(rl)
stale = "0000000000000000"
try:
    verify_plan(index, stale)
except StalePlanError:
    print("  plan was written against a document we no longer have.")
    print("  the fix is to re-render and re-review, not to apply anyway:")
    print("   ", index.render(para_ids=[19])[:74], "...")

section("StalePlanError is a RedlineError")
from docx_redline import RedlineError

print("  issubclass(StalePlanError, RedlineError):", issubclass(StalePlanError, RedlineError))

section("a worked round trip through a file")
rl = fresh()
index = ParagraphIndex(rl)
before = index.fingerprint()
index.apply([RedlineEdit(19, "thirty (30) days", "forty-five (45) days")])
path = OUT / "15_fingerprint.docx"
rl.save(path)
print("  saved       :", fingerprint(path))
print("  reject-all  :", end=" ")
reverted = Redliner(path)
reverted.reject_all()
print(fingerprint(reverted), "== original", fingerprint(reverted) == before)
