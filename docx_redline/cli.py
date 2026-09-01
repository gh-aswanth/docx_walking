# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Command line front end:  ``python -m docx_redline <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .editing.compare import redline_files
from .editing.ops import apply_operations, validate
from .editing.redline import RedlineError, Redliner
from .planning.agent import REVIEWER_CHOICES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docx-redline",
        description="Produce and manage Word tracked changes in .docx files.",
    )
    parser.add_argument("--version", action="version", version=f"docx-redline {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--author", default="Redline", help="revision author name")
    common.add_argument(
        "--date", default=None, help="ISO-8601 UTC stamp, e.g. 2026-08-19T00:00:00Z"
    )

    p = sub.add_parser("compare", parents=[common], help="redline ORIGINAL against REVISED")
    p.add_argument("original")
    p.add_argument("revised")
    p.add_argument("-o", "--output", required=True)
    p.add_argument(
        "--similarity",
        type=float,
        default=0.45,
        help="below this ratio a paragraph pair is treated as unrelated",
    )

    p = sub.add_parser("apply", parents=[common], help="apply a JSON edit plan")
    p.add_argument("source")
    p.add_argument("plan", help='JSON file: a list of ops, or {"operations": [...]}')
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--lenient", action="store_true", help="do not fail when an op matches nothing")

    p = sub.add_parser(
        "pipeline",
        parents=[common],
        help="clause-aware run: propose action items, apply them, renumber, verify",
    )
    p.add_argument("source")
    p.add_argument("-o", "--output", required=True)
    p.add_argument(
        "--actions", default=None, help="action-item JSON; read if it exists, written if not"
    )
    p.add_argument("--reviewer", default="rules", choices=list(REVIEWER_CHOICES))
    p.add_argument("--model", default=None, help="model override for a model-backed reviewer")
    p.add_argument("--brief", default=None, help="review instructions for the reviewer")
    p.add_argument("--report", default=None, help="write the JSON run report here")
    p.add_argument(
        "--no-renumber",
        action="store_true",
        help="apply the actions but leave numbering and cross-references alone",
    )
    p.add_argument(
        "--revised", default=None, help="a second .docx to diff against before the action items run"
    )
    p.add_argument(
        "--comment",
        action="append",
        default=[],
        metavar="CLAUSE=TEXT",
        help="attach a review comment to a clause (repeatable)",
    )
    p.add_argument(
        "--no-explain",
        action="store_true",
        help="do not write each action's rationale into the .docx as a comment",
    )

    p = sub.add_parser(
        "full",
        parents=[common],
        help="everything at once: compare + action items + comments, renumbered and verified",
    )
    p.add_argument("source")
    p.add_argument("-o", "--output", required=True)
    p.add_argument(
        "--actions",
        default=None,
        metavar="FILE",
        help="JSON edit plan to run: a list of action items, or "
        '{"action_items": [...]}. Read only -- never rewritten.',
    )
    p.add_argument(
        "--action",
        action="append",
        default=[],
        metavar="JSON",
        help="a single action item as inline JSON (repeatable), e.g. "
        '\'{"type":"move_clause","clause":"12.1","after_clause":"4.1"}\'',
    )
    p.add_argument(
        "--revised",
        default=None,
        metavar="FILE",
        help="a second .docx to diff in first, Word-Compare style",
    )
    p.add_argument(
        "--reviewer",
        default=None,
        choices=list(REVIEWER_CHOICES),
        help="ask a reviewer for the action items instead of supplying them",
    )
    p.add_argument(
        "--provider",
        default="claude",
        choices=["claude", "openai"],
        help="which engine --reviewer chunked drives",
    )
    p.add_argument(
        "--segment-tokens", type=int, default=25_000, help="target size of each reviewed segment"
    )
    p.add_argument("--concurrency", type=int, default=6, help="segments reviewed in parallel")
    p.add_argument(
        "--no-triage",
        action="store_true",
        help="review every segment instead of selecting with a cheap first pass",
    )
    p.add_argument(
        "--min-coverage",
        type=float,
        default=0.35,
        help="least share of the document that must get a full read",
    )
    p.add_argument(
        "--max-actions",
        type=int,
        default=None,
        help="keep at most this many action items, most severe first",
    )
    p.add_argument(
        "--cache-dir", default=None, help="where per-segment replies are cached so a run can resume"
    )
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--refresh", action="store_true", help="ignore cached segment replies")
    p.add_argument(
        "--merge-report", default=None, help="write the segment/merge reconciliation report here"
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="seconds to wait for one model call before giving up",
    )
    p.add_argument(
        "--no-stream",
        action="store_true",
        help="do not stream the model response (streaming avoids read timeouts)",
    )
    p.add_argument("--model", default=None, help="model override for a model-backed reviewer")
    p.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--brief", default=None, help="review instructions for the reviewer")
    p.add_argument(
        "--comment",
        action="append",
        default=[],
        metavar="CLAUSE=TEXT",
        help="attach a comment to a clause (repeatable); "
        "use find=PHRASE=TEXT to anchor on a phrase",
    )
    p.add_argument(
        "--comments-file",
        default=None,
        metavar="FILE",
        help="JSON list of {clause|find, text} comments",
    )
    p.add_argument("--report", default=None, help="write the JSON run report here")
    p.add_argument(
        "--similarity",
        type=float,
        default=0.45,
        help="below this ratio a compared paragraph pair is treated as unrelated",
    )
    p.add_argument(
        "--no-renumber",
        action="store_true",
        help="apply the edits but leave numbering and cross-references alone",
    )
    p.add_argument(
        "--strict", action="store_true", help="abort on the first action that cannot be applied"
    )
    p.add_argument(
        "--no-explain",
        action="store_true",
        help="do not write each action's rationale into the .docx as a comment",
    )

    p = sub.add_parser("doctor", help="check credentials, model and latency with one tiny call")
    p.add_argument("--provider", default="openai", choices=["claude", "openai"])
    p.add_argument("--model", default=None)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--effort", default="low", choices=["low", "medium", "high", "xhigh", "max"])

    p = sub.add_parser("accept", help="accept every tracked change")
    p.add_argument("source")
    p.add_argument("-o", "--output", required=True)

    p = sub.add_parser("reject", help="reject every tracked change")
    p.add_argument("source")
    p.add_argument("-o", "--output", required=True)

    p = sub.add_parser("summary", help="list tracked changes in a document")
    p.add_argument("source")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("validate", help="check a JSON edit plan without running it")
    p.add_argument("plan")
    return parser


def _load_plan(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        return data.get("operations", [])
    return data


def _doctor(args) -> int:
    """One minimal round trip, timed -- the fastest way to tell what is wrong.

    A review call is big, slow and easy to blame on the wrong thing. This sends
    the smallest possible request instead, so credentials, model name, network
    and latency each fail distinguishably.
    """
    import time

    from .planning.agent import (
        ACTION_OUTPUT,
        RedlineCredentialsError,
        default_model_for,
        get_reviewer,
    )

    model = args.model or default_model_for(args.provider)
    print(f"provider : {args.provider}")
    print(f"model    : {model}")
    print(f"effort   : {args.effort}   timeout: {args.timeout}s")

    reviewer = get_reviewer(
        args.provider,
        effort=args.effort,
        max_tokens=512,
        timeout=args.timeout,
        **({"model": args.model} if args.model else {}),
    )

    print("\n1. resolving credentials ...", end=" ", flush=True)
    try:
        _ = reviewer.client  # the probe: building it is what resolves credentials
    except RedlineCredentialsError as exc:
        print("FAIL")
        print(f"   {exc}")
        return 2
    print("ok")

    print("2. sending a minimal request ...", flush=True)
    ticks = {"n": 0}

    def tick(_event):
        ticks["n"] += 1
        if ticks["n"] == 1:
            print(f"   first event after {time.monotonic() - start:.1f}s", flush=True)

    start = time.monotonic()
    try:
        reply = reviewer.emit(
            system="You produce structured output for a test. Return no action items.",
            cached="<agreement>\n1. Test. This is a connectivity check.\n</agreement>",
            variable="<review_brief>\nReturn an empty list.\n</review_brief>",
            output=ACTION_OUTPUT,
            on_event=tick,
        )
    except Exception as exc:
        elapsed = time.monotonic() - start
        print(f"   FAIL after {elapsed:.1f}s: {type(exc).__name__}: {str(exc)[:200]}")
        if "timeout" in type(exc).__name__.lower():
            print("   → the model did not answer in time. Try --effort low, a smaller")
            print("     --max-actions, or a faster model; raise --timeout if it is just slow.")
        return 1

    elapsed = time.monotonic() - start
    print(f"   ok in {elapsed:.1f}s ({ticks['n']} stream events)")
    print(f"   model reported: {reply.model}")
    print(f"   usage: {reply.usage}")
    print("\nA real review sends far more input and asks for far more output, so")
    print(f"expect roughly {elapsed * 8:.0f}-{elapsed * 30:.0f}s per segment at this effort.")
    return 0


def _build_reviewer(args, get_reviewer):
    """Construct the reviewer named on the command line, with its options."""
    if not args.reviewer:
        return None
    if args.reviewer == "rules":
        return get_reviewer("rules")
    if args.reviewer == "chunked":
        engine_options = {
            "effort": args.effort,
            "timeout": args.timeout,
            "stream": not args.no_stream,
        }
        if args.model:
            engine_options["model"] = args.model
        return get_reviewer(
            "chunked",
            engine=get_reviewer(args.provider, **engine_options),
            segment_tokens=args.segment_tokens,
            concurrency=args.concurrency,
            triage=not args.no_triage,
            min_coverage=args.min_coverage,
            max_actions=args.max_actions,
            cache_dir=args.cache_dir,
            use_cache=not args.no_cache,
            refresh=args.refresh,
            on_progress=_print_progress,
        )
    options = {"effort": args.effort}
    if getattr(args, "timeout", None) is not None:
        options["timeout"] = args.timeout
    if getattr(args, "no_stream", False):
        options["stream"] = False
    if args.model:
        options["model"] = args.model
    return get_reviewer(args.reviewer, **options)


def _print_progress(progress) -> None:
    if progress.phase == "map":
        where = f"{progress.done}/{progress.total}" if progress.total else "     "
        print(
            f"  [{progress.status or 'map':<7}] {progress.segment or '':<5} "
            f"{where}  {progress.items or '':>3} {progress.detail}",
            flush=True,
        )
    else:
        print(f"  [{progress.phase:<7}] {progress.detail}")


def _format_merge(merge: dict) -> str:
    s = merge.get("summary", {})
    return (
        f"{s.get('segments', 0)} segments ({s.get('reviewed', 0)} reviewed, "
        f"{s.get('skipped', 0)} skipped): {s.get('proposed', 0)} proposed -> "
        f"{s.get('kept', 0)} kept ({s.get('dropped', 0)} duplicate, "
        f"{s.get('conflicts', 0)} conflicting, {s.get('unresolved', 0)} unresolvable)"
    )


def _inline_actions(raw: list[str]) -> list[dict] | None:
    """Parse repeated ``--action '{...}'`` flags into action items."""
    if not raw:
        return None
    items = []
    for index, blob in enumerate(raw):
        try:
            item = json.loads(blob)
        except json.JSONDecodeError as exc:
            raise RedlineError(f"--action #{index + 1} is not valid JSON: {exc}") from exc
        if not isinstance(item, dict):
            raise RedlineError(
                f"--action #{index + 1} must be a JSON object, got {type(item).__name__}"
            )
        item.setdefault("id", f"CLI-{index + 1:03d}")
        item.setdefault("rationale", "supplied on the command line")
        item.setdefault("severity", "medium")
        items.append(item)
    return items


def _collect_comments(flags: list[str], path: str | None) -> list[dict]:
    """``CLAUSE=TEXT`` / ``find=PHRASE=TEXT`` flags plus an optional JSON file."""
    comments: list[dict] = []
    if path:
        loaded = json.loads(Path(path).read_text())
        comments.extend(loaded if isinstance(loaded, list) else loaded.get("comments", []))
    for raw in flags:
        target, sep, text = raw.partition("=")
        if not sep or not text.strip():
            raise RedlineError(f"--comment expects CLAUSE=TEXT, got {raw!r}")
        if target == "find":
            phrase, sep2, text = text.partition("=")
            if not sep2:
                raise RedlineError(f"--comment expects find=PHRASE=TEXT, got {raw!r}")
            comments.append({"find": phrase, "text": text})
        else:
            comments.append({"clause": target, "text": text})
    return comments


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "compare":
        stats = redline_files(
            args.original,
            args.revised,
            args.output,
            author=args.author,
            date=args.date,
            similarity_floor=args.similarity,
        )
        print(stats.format())
        print(f"wrote {args.output}")
        return 0

    if args.command == "apply":
        rl = Redliner(args.source, author=args.author, date=args.date)
        results = apply_operations(rl, _load_plan(args.plan), strict=not args.lenient)
        for op_result in results:
            print(f"{op_result.op:<20} x{op_result.applied}  {op_result.detail}")
        rl.save(args.output)
        print(f"wrote {args.output}")
        return 0

    if args.command == "pipeline":
        from .planning.agent import get_reviewer
        from .planning.pipeline import DEFAULT_BRIEF, RedlinePipeline

        reviewer = (
            get_reviewer(args.reviewer, model=args.model)
            if args.model and args.reviewer != "rules"
            else args.reviewer
        )
        pipeline = RedlinePipeline(
            args.source,
            author=args.author,
            date=args.date,
            reviewer=reviewer,
            brief=args.brief or DEFAULT_BRIEF,
            renumber=not args.no_renumber,
            explain=not args.no_explain,
            revised=args.revised,
            comments=_collect_comments(args.comment, None),
            on_stage=lambda s: print(f"  [{'ok ' if s.ok else 'FAIL'}] {s.name:<10} {s.detail}"),
        )
        result = pipeline.run(args.output, actions_file=args.actions, report_path=args.report)
        print()
        print(result.plan.format())
        for name, passed, _detail in result.checks:
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"wrote {args.output}")
        return 0 if result.ok else 1

    if args.command == "full":
        from .planning.agent import RedlineCredentialsError, get_reviewer
        from .planning.pipeline import DEFAULT_BRIEF, full_redline

        actions = _inline_actions(args.action) or args.actions
        if actions is None and args.reviewer is None and not (args.comment or args.comments_file):
            print(
                "error: nothing to do -- pass --actions/--action, --revised, "
                "--reviewer or --comment",
                file=sys.stderr,
            )
            return 2
        reviewer = _build_reviewer(args, get_reviewer)

        try:
            result = full_redline(
                args.source,
                args.output,
                revised=args.revised,
                actions=actions,
                reviewer=reviewer,
                brief=args.brief or DEFAULT_BRIEF,
                comments=_collect_comments(args.comment, args.comments_file),
                author=args.author,
                date=args.date,
                renumber=not args.no_renumber,
                strict=args.strict,
                explain=not args.no_explain,
                similarity_floor=args.similarity,
                report_path=args.report,
                on_stage=lambda st: print(
                    f"  [{'ok ' if st.ok else 'FAIL'}] {st.name:<10} {st.detail}"
                ),
            )
        except RedlineCredentialsError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        print()
        merge = (result.proposal.merge if result.proposal else None) or {}
        if merge:
            print("  " + _format_merge(merge))
            if args.merge_report:
                Path(args.merge_report).write_text(json.dumps(merge, indent=2) + "\n")
                print(f"  merge report -> {args.merge_report}")
        print(result.plan.format())
        for change in result.plan.renumbered:
            print(f"    {change['from']:>6}  ->  {change['to']:<6}  {change['title'][:52]}")
        for ref in result.plan.references:
            print(f"    {ref['context']}")
        print()
        for name, passed, detail in result.checks:
            print(
                f"  [{'PASS' if passed else 'FAIL'}] {name}"
                + (f"  ({detail})" if detail and not passed else "")
            )
        print(f"\nwrote {args.output}")
        return 0 if result.ok else 1

    if args.command == "doctor":
        return _doctor(args)

    if args.command in ("accept", "reject"):
        rl = Redliner(args.source, track_changes=False)
        (rl.accept_all if args.command == "accept" else rl.reject_all)()
        rl.save(args.output)
        print(f"wrote {args.output}")
        return 0

    if args.command == "summary":
        summary = Redliner(args.source, track_changes=False).summary()
        if args.json:
            print(json.dumps([r.__dict__ for r in summary.revisions], indent=2))
        else:
            print(summary.format(limit=args.limit))
        return 0

    if args.command == "validate":
        problems = validate(_load_plan(args.plan))
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        print("plan is valid")
        return 0

    return 1  # pragma: no cover


def _entry() -> None:  # pragma: no cover
    try:
        sys.exit(main())
    except RedlineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":  # pragma: no cover
    _entry()
