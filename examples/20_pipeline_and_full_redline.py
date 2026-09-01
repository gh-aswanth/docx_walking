"""20 · RedlinePipeline and full_redline — every option.

    EXTRACT -> PROPOSE -> VALIDATE -> COMPARE -> PLAN -> COMMENT
            -> RENUMBER -> VERIFY -> REPORT

Order is not negotiable: the compare runs first so scripted actions address the
document the diff produced; comments run last so they anchor to finished text;
renumbering runs once, at the very end, over the combined result.
"""

import json

from _shared import OUT, PLAN, SOURCE, banner, section

from docx_redline import RedlinePipeline, full_redline

banner("20 · Pipeline and full_redline")

section("stage by stage — every stage returns plain data")
pipeline = RedlinePipeline(SOURCE, author="AI Contract Reviewer", reviewer="rules")
tree = pipeline.extract()
print("  extract  ->", len(tree.all()), "clauses,", len(tree.sections), "sections")
proposal = pipeline.propose(PLAN)
print(
    "  propose  ->",
    len(proposal.action_items),
    "action items from",
    PLAN.name,
    f"(source={proposal.source!r})",
)
print("  validate ->", pipeline.validate(proposal) or "no problems")
rl, plan = pipeline.apply(proposal)
print("  apply    ->", plan.format().splitlines()[0])
checks = pipeline.verify(rl)
for name, ok, _detail in checks:
    print(f"  verify   -> [{'PASS' if ok else 'FAIL'}] {name}")
result = pipeline.write(rl, OUT / "20_staged.docx", report_path=OUT / "20_staged.json")
print("  write    -> ok =", result.ok)

section("on_stage — a callback per stage, for progress reporting")
seen = []
RedlinePipeline(SOURCE, reviewer="rules", on_stage=lambda log: seen.append(log.name)).run(
    OUT / "20_progress.docx", actions_file=PLAN, write_actions=False
)
print("  stages:", " -> ".join(seen))

section("constructor options")
for label, kwargs in [
    ("renumber=True  (default)", {}),
    ("renumber=False          ", {"renumber": False}),
    ("explain=False           ", {"explain": False}),
    ("strict=True             ", {"strict": True}),
    ("similarity_floor=0.80   ", {"similarity_floor": 0.80}),
    ("author= / date= pinned  ", {"author": "Deal Team", "date": "2026-01-01T00:00:00Z"}),
]:
    p = RedlinePipeline(SOURCE, reviewer="rules", **kwargs)
    r = p.run(OUT / "20_opt.docx", actions_file=PLAN, write_actions=False)
    print(
        f"  {label} -> ok={r.ok}  renumbered={len(r.plan.renumbered)} refs={len(r.plan.references)}"
    )

section("comments= — annotate the finished redline")
result = full_redline(
    SOURCE,
    OUT / "20_comments.docx",
    actions=str(PLAN),
    comments=[
        {"clause": "10.2", "text": "Confirm the cap multiple with finance."},
        {"find": "quarterly in arrears", "text": "Billing cadence changed - flag revenue ops."},
    ],
    explain=False,
)
print("  ok =", result.ok, "| comments written:", 2)

section("actions= takes three forms, and wins over reviewer=")
print("  a list of dicts")
full_redline(
    SOURCE,
    OUT / "20_list.docx",
    actions=[{"type": "move_clause", "clause": "12.1", "after_clause": "4.1"}],
)
print("  a path (str or Path) --", PLAN.name)
full_redline(SOURCE, OUT / "20_path.docx", actions=str(PLAN))
print("  or reviewer= lets the offline rules decide")
full_redline(SOURCE, OUT / "20_reviewer.docx", reviewer="rules")

section("revised= — diff a counterparty markup in first")
counterparty = OUT / "20_counterparty.docx"
from docx_redline import Redliner

cp = Redliner(SOURCE, author="Counterparty", track_changes=False)
cp.replace_text("thirty (30) days", "sixty (60) days", count=None)
cp.accept_all()
cp.save(counterparty)
result = full_redline(
    SOURCE,
    OUT / "20_compare_first.docx",
    revised=counterparty,
    actions=[
        {
            "type": "replace_text",
            "find": "sixty (60) days",
            "replace": "forty-five (45) days",
            "all": True,
        }
    ],
)
print("  the action matched text the compare introduced -> ok =", result.ok)

section("report_path / actions_path — the machine-readable outputs")
result = full_redline(
    SOURCE,
    OUT / "20_reported.docx",
    actions=str(PLAN),
    report_path=OUT / "20_report.json",
    actions_path=OUT / "20_actions.json",
)
report = json.loads((OUT / "20_report.json").read_text(encoding="utf-8"))
print("  report keys :", list(report))
print(
    "  actions.json:",
    len(json.loads((OUT / "20_actions.json").read_text(encoding="utf-8"))["action_items"]),
    "items",
)
print(
    "  PipelineResult fields:",
    [
        "source",
        "output",
        "compare",
        "actions_path",
        "report_path",
        "proposal",
        "plan",
        "stages",
        "checks",
    ],
)
print("  checks      :", sum(1 for c in result.checks if c[1]), "of", len(result.checks), "passed")

section("every full_redline option, for reference")
print("""  full_redline(source, output, *,
      revised=None, actions=None, reviewer=None, brief=DEFAULT_BRIEF,
      comments=None, author="AI Contract Reviewer", date=None,
      renumber=True, strict=False, explain=True, similarity_floor=0.45,
      report_path=None, actions_path=None, on_stage=None)""")
print("  passing none of revised/actions/reviewer raises rather than writing")
print("  an unchanged file:")
try:
    full_redline(SOURCE, OUT / "20_nothing.docx")
except Exception as exc:
    print(f"    {type(exc).__name__}: {exc}")
