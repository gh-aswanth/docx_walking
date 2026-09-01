"""25 · Every CLI subcommand and flag, run for real.

    docx-redline {full,pipeline,compare,apply,accept,reject,summary,validate,doctor}

Four spellings run the same command:
    uv run docx_redline ...      uv run docx-redline ...
    python -m docx_redline ...   python docx_redline/__main__.py ...

Exit codes: 0 success, 1 a stage or check failed, 2 bad input.
"""

import json
import subprocess
import sys

from _shared import CHILD_ENV, OUT, PLAN, ROOT, SOURCE, banner, section

banner("25 · CLI")
PY = sys.executable


def short(arg):
    text = str(arg)
    return text.replace(str(ROOT) + "/", "") if text.startswith(str(ROOT)) else text


def run(*args, expect=0, show=4):
    proc = subprocess.run(
        [PY, "-m", "docx_redline", *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=CHILD_ENV,
    )
    tag = "ok " if proc.returncode == expect else "!! "
    print(f"  {tag}exit={proc.returncode}  docx-redline {' '.join(short(a) for a in args)[:86]}")
    for line in (proc.stdout or proc.stderr).strip().splitlines()[:show]:
        print(f"       {short(line)[:90]}")
    return proc


section("--version and --help")
run("--version")

section("pipeline — clause-aware run")
run(
    "pipeline",
    SOURCE,
    "-o",
    OUT / "25_pipeline.docx",
    "--actions",
    PLAN,
    "--author",
    "AI Contract Reviewer",
    "--date",
    "2026-01-01T00:00:00Z",
    "--report",
    OUT / "25_pipeline.json",
)
run(
    "pipeline",
    SOURCE,
    "-o",
    OUT / "25_pipeline_plain.docx",
    "--actions",
    PLAN,
    "--no-renumber",
    "--no-explain",
)
run(
    "pipeline",
    SOURCE,
    "-o",
    OUT / "25_pipeline_rules.docx",
    "--reviewer",
    "rules",
    "--brief",
    "Review for the Customer.",
    "--actions",
    OUT / "25_written_plan.json",
)
print("       (--actions is read if it exists, written if it does not)")

section("full — compare + action items + comments, in one pass")
run(
    "full",
    SOURCE,
    "-o",
    OUT / "25_full.docx",
    "--actions",
    PLAN,
    "--comment",
    "10.2=Confirm the cap with finance.",
    "--comment",
    "find=quarterly in arrears=Flag to revenue ops.",
    "--report",
    OUT / "25_full.json",
    "--similarity",
    "0.45",
)
run(
    "full",
    SOURCE,
    "-o",
    OUT / "25_full_inline.docx",
    "--action",
    json.dumps({"type": "move_clause", "clause": "12.1", "after_clause": "4.1"}),
    "--action",
    json.dumps({"type": "reorder_clauses", "section": "8", "order": ["8.1", "8.3", "8.2"]}),
)
run(
    "full", SOURCE, "-o", OUT / "25_full_strict.docx", "--actions", PLAN, "--strict", "--no-explain"
)
print("       chunked flags (need an API key, shown for reference):")
print("         --reviewer chunked --provider claude --segment-tokens 25000")
print("         --concurrency 6 --no-triage --min-coverage 0.35 --max-actions 40")
print("         --cache-dir .cache --no-cache --refresh --merge-report merge.json")
print("         --model M --effort high --timeout 300 --no-stream")

section("compare — Word Compare, two files in")
revised = OUT / "25_revised.docx"
from docx_redline import Redliner

cp = Redliner(SOURCE, track_changes=False)
cp.replace_text("thirty (30) days", "sixty (60) days", count=None)
cp.accept_all()
cp.save(revised)
run(
    "compare",
    SOURCE,
    revised,
    "-o",
    OUT / "25_compare.docx",
    "--author",
    "Compare Bot",
    "--date",
    "2026-01-01T00:00:00Z",
    "--similarity",
    "0.45",
)

section("apply — a declarative op plan")
ops_plan = OUT / "25_ops.json"
ops_plan.write_text(
    json.dumps(
        {
            "operations": [
                {"op": "replace_text", "old": "thirty (30) days", "new": "forty-five (45) days"},
                {"op": "comment", "match": "10.2  Liability Cap", "text": "Check with finance."},
            ]
        },
        indent=2,
    ),
    encoding="utf-8",
)
run("apply", SOURCE, ops_plan, "-o", OUT / "25_apply.docx", "--author", "Ops")
bad_ops = OUT / "25_ops_bad.json"
bad_ops.write_text(
    json.dumps([{"op": "replace_text", "old": "nope", "new": "x"}]), encoding="utf-8"
)
run("apply", SOURCE, bad_ops, "-o", OUT / "25_apply_lenient.docx", "--lenient")

section("accept / reject")
run("accept", OUT / "25_full.docx", "-o", OUT / "25_accepted.docx")
run("reject", OUT / "25_full.docx", "-o", OUT / "25_rejected.docx")

section("summary — --limit and --json")
run("summary", OUT / "25_full.docx", "--limit", "3")
proc = run("summary", OUT / "25_full.docx", "--json", show=0)
revisions = json.loads(proc.stdout)
print(f"       {len(revisions)} revisions, each with keys {list(revisions[0])}")
print(f"       first: {revisions[0]}")

section("validate — schema-check a plan without opening a document")
run("validate", ops_plan)
run("validate", bad_ops)

section("doctor — one tiny call to check credentials, model and latency")
print("       docx-redline doctor --provider claude --model M --effort low --timeout 30")
print("       (skipped here: it makes a real API call)")

section("exit codes")
broken = OUT / "25_broken.json"
broken.write_text(json.dumps([{"op": "replace_txt", "old": "a", "new": "b"}]), encoding="utf-8")
run("validate", broken, expect=1)  # validate reports problems -> 1
run("apply", SOURCE, broken, "-o", OUT / "25_never.docx", expect=2)  # bad input -> 2
print("  0 = success, 1 = a stage or check failed, 2 = bad input")
print(
    "  a schema-invalid plan aborts before the document is opened:",
    not (OUT / "25_never.docx").exists(),
)
