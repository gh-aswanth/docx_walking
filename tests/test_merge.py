"""Reconciling proposals from segments that never saw each other.

Every case here is one where applying the raw union would not fail loudly. It
would report ``applied`` on both items and hand back a document that is quietly
wrong -- so the assertions are about what survives, and about the reason
recorded for what did not.
"""

import pytest

from docx_redline.planning.actions import validate_actions
from docx_redline.planning.merge import SegmentResult, reduce_segments
from docx_redline.structure.clauses import ClauseTree
from docx_redline.structure.segments import segment_document


@pytest.fixture
def tree(rl_agreement) -> ClauseTree:
    return ClauseTree(rl_agreement.document.element.body)


@pytest.fixture
def whole(tree):
    """One segment covering the document, so ownership never interferes."""
    return segment_document(tree.root, budget_tokens=100_000, tree=tree)[0]


def item(**kwargs) -> dict:
    base = {"id": "AI-001", "rationale": "r", "severity": "medium"}
    base.update(kwargs)
    return base


def results(whole, *batches) -> list[SegmentResult]:
    return [SegmentResult(segment=whole, items=list(batch)) for batch in batches]


def kinds(items) -> list[str]:
    return [i["type"] for i in items]


def reasons(report) -> str:
    return " | ".join(entry["reason"] for entry in report.dropped + report.unresolved) + " | ".join(
        entry["rule"] for entry in report.conflicts
    )


# ---------------------------------------------------------------------------
# ids
# ---------------------------------------------------------------------------
def test_colliding_ids_merge_cleanly(tree, whole):
    """Every segment restarts at AI-001; duplicate ids abort the entire plan."""
    merged, report = reduce_segments(
        tree,
        results(
            whole,
            [
                item(
                    id="AI-001",
                    type="replace_text",
                    clause="2.2",
                    find="thirty (30) days",
                    replace="45 days",
                )
            ],
            [
                item(
                    id="AI-001",
                    type="replace_text",
                    clause="3.2",
                    find="renews automatically",
                    replace="renews on notice",
                )
            ],
        ),
    )
    assert len(merged) == 2
    assert len({i["id"] for i in merged}) == 2
    assert validate_actions(merged) == []
    assert report.kept == 2


def test_provenance_survives_re_identification(tree, whole):
    merged, report = reduce_segments(
        tree,
        results(
            whole, [item(id="AI-007", type="delete_text", clause="3.2", find=" automatically")]
        ),
    )
    entry = report.provenance[merged[0]["id"]]
    assert entry["original_id"] == "AI-007"
    assert entry["segment"] == whole.id
    assert merged[0]["note"] == whole.id


# ---------------------------------------------------------------------------
# ownership
# ---------------------------------------------------------------------------
def test_a_segment_cannot_edit_outside_itself(tree):
    """Boundary context is read-only; without this it gets edited twice."""
    first, second = segment_document(tree.root, budget_tokens=40, tree=tree)[:2]
    outside = sorted(second.labels)[0]
    merged, report = reduce_segments(
        tree,
        [SegmentResult(first, [item(type="replace_text", clause=outside, find="x", replace="y")])],
    )
    assert merged == []
    assert "outside this segment" in reasons(report)


def test_structural_actions_are_dropped_without_clause_numbers(tree, whole):
    object.__setattr__(whole, "strategy", "windows")
    merged, report = reduce_segments(
        tree, results(whole, [item(type="move_clause", clause="4.1", after_clause="3.1")])
    )
    assert merged == []
    assert "clause numbering" in reasons(report)


# ---------------------------------------------------------------------------
# dedupe
# ---------------------------------------------------------------------------
def test_identical_proposals_collapse(tree, whole):
    same = item(type="replace_text", clause="2.2", find="thirty (30) days", replace="45 days")
    merged, report = reduce_segments(tree, results(whole, [same], [dict(same, id="AI-002")]))
    assert len(merged) == 1
    assert "identical to" in reasons(report)


def test_dedupe_does_not_collapse_distinct_inserts(tree, whole):
    """A four-field key would merge every insert_clause in the document into one:
    `find` and `replace` are absent on all of them."""
    merged, _ = reduce_segments(
        tree,
        results(
            whole,
            [
                item(id="A", type="insert_clause", after_clause="2.1", text="First new clause."),
                item(id="B", type="insert_clause", after_clause="3.1", text="Second new clause."),
            ],
        ),
    )
    assert kinds(merged) == ["insert_clause", "insert_clause"]


def test_severity_is_not_part_of_an_action_identity(tree, whole):
    a = item(
        type="replace_text",
        clause="2.2",
        find="thirty (30) days",
        replace="45 days",
        severity="low",
    )
    b = dict(a, id="AI-002", severity="critical", rationale="different wording")
    merged, _ = reduce_segments(tree, results(whole, [a], [b]))
    assert len(merged) == 1


# ---------------------------------------------------------------------------
# conflicts
# ---------------------------------------------------------------------------
def test_one_structural_action_per_clause(tree, whole):
    merged, report = reduce_segments(
        tree,
        results(
            whole,
            [item(id="A", type="move_clause", clause="4.1", after_clause="3.1", severity="high")],
            [item(id="B", type="move_clause", clause="4.1", after_clause="2.1", severity="low")],
        ),
    )
    assert len(merged) == 1
    assert merged[0]["after_clause"] == "3.1", "the more severe proposal should win"
    assert "already claims this clause" in reasons(report)


def test_a_delete_beats_edits_to_the_same_clause(tree, whole):
    merged, report = reduce_segments(
        tree,
        results(
            whole,
            [item(id="A", type="delete_clause", clause="2.2", severity="high")],
            [
                item(
                    id="B",
                    type="replace_text",
                    clause="2.2",
                    find="thirty (30) days",
                    replace="45 days",
                    severity="low",
                )
            ],
        ),
    )
    assert kinds(merged) == ["delete_clause"]
    assert "deletes" in reasons(report)


def test_a_rewrite_suppresses_piecemeal_edits_to_the_same_clause(tree, whole):
    merged, report = reduce_segments(
        tree,
        results(
            whole,
            [
                item(
                    id="A",
                    type="rewrite_clause",
                    clause="2.2",
                    text="Invoicing. Payment is due on receipt.",
                    severity="high",
                )
            ],
            [
                item(
                    id="B",
                    type="replace_text",
                    clause="2.2",
                    find="thirty (30) days",
                    replace="45 days",
                    severity="low",
                )
            ],
        ),
    )
    assert kinds(merged) == ["rewrite_clause"]
    assert "rewritten wholesale" in reasons(report)


def test_two_rewrites_of_one_clause_keep_the_severe_one(tree, whole):
    merged, _ = reduce_segments(
        tree,
        results(
            whole,
            [item(id="A", type="rewrite_clause", clause="2.2", text="Version A.", severity="low")],
            [
                item(
                    id="B",
                    type="rewrite_clause",
                    clause="2.2",
                    text="Version B.",
                    severity="critical",
                )
            ],
        ),
    )
    assert len(merged) == 1 and merged[0]["text"] == "Version B."


def test_disjoint_edits_to_one_clause_both_survive(tree, whole):
    """Only genuine overlap is a conflict -- dropping disjoint edits loses review."""
    merged, _ = reduce_segments(
        tree,
        results(
            whole,
            [item(id="A", type="replace_text", clause="2.2", find="Invoicing", replace="Billing")],
            [
                item(
                    id="B",
                    type="replace_text",
                    clause="2.2",
                    find="thirty (30) days",
                    replace="45 days",
                )
            ],
        ),
    )
    assert len(merged) == 2


def test_overlapping_edits_to_one_clause_are_reduced_to_one(tree, whole):
    merged, report = reduce_segments(
        tree,
        results(
            whole,
            [
                item(
                    id="A",
                    type="replace_text",
                    clause="2.2",
                    find="thirty (30) days",
                    replace="45 days",
                    severity="high",
                )
            ],
            [
                item(
                    id="B",
                    type="replace_text",
                    clause="2.2",
                    find="within thirty (30) days",
                    replace="within 45 days",
                    severity="low",
                )
            ],
        ),
    )
    assert len(merged) == 1
    assert "overlap" in reasons(report)


def test_one_insertion_per_anchor(tree, whole):
    """Two insertions at one anchor apply in reverse order, silently."""
    merged, report = reduce_segments(
        tree,
        results(
            whole,
            [
                item(
                    id="A",
                    type="insert_text",
                    clause="2.2",
                    anchor="days",
                    text=" of receipt",
                    severity="high",
                )
            ],
            [
                item(
                    id="B",
                    type="insert_text",
                    clause="2.2",
                    anchor="days",
                    text=" of invoice",
                    severity="low",
                )
            ],
        ),
    )
    assert len(merged) == 1 and merged[0]["text"] == " of receipt"
    assert "anchor" in reasons(report)


def test_one_reorder_per_section(tree, whole):
    merged, _report = reduce_segments(
        tree,
        results(
            whole,
            [
                item(
                    id="A",
                    type="reorder_clauses",
                    section="2",
                    order=["2.3", "2.1", "2.2"],
                    severity="high",
                )
            ],
            [
                item(
                    id="B",
                    type="reorder_clauses",
                    section="2",
                    order=["2.2", "2.1", "2.3"],
                    severity="low",
                )
            ],
        ),
    )
    assert len(merged) == 1 and merged[0]["order"] == ["2.3", "2.1", "2.2"]


def test_an_action_targeting_a_deleted_subtree_is_dropped(tree, whole):
    merged, report = reduce_segments(
        tree,
        results(
            whole,
            [item(id="A", type="delete_section", section="2", severity="high")],
            [item(id="B", type="insert_clause", after_clause="2.1", text="New.", severity="low")],
        ),
    )
    assert kinds(merged) == ["delete_section"]
    assert "deletes" in reasons(report)


# ---------------------------------------------------------------------------
# pre-flight
# ---------------------------------------------------------------------------
def test_a_hallucinated_clause_never_reaches_the_planner(tree, whole):
    merged, report = reduce_segments(
        tree, results(whole, [item(type="delete_clause", clause="99.9")])
    )
    assert merged == []
    assert "is not a clause" in reasons(report)


def test_a_misquoted_find_is_caught_before_anything_is_edited(tree, whole):
    merged, report = reduce_segments(
        tree,
        results(
            whole,
            [item(type="replace_text", clause="2.2", find="ninety (90) days", replace="45 days")],
        ),
    )
    assert merged == []
    assert "does not occur in clause 2.2" in reasons(report)


def test_an_ambiguous_unscoped_quote_is_caught(tree, whole):
    merged, report = reduce_segments(
        tree, results(whole, [item(type="replace_text", find="Order Form", replace="Order")])
    )
    assert merged == []
    assert "ambiguous" in reasons(report)


def test_a_unique_unscoped_quote_survives(tree, whole):
    merged, _ = reduce_segments(
        tree,
        results(
            whole,
            [
                item(
                    type="replace_text", find="Delaware law governs", replace="New York law governs"
                )
            ],
        ),
    )
    assert len(merged) == 1


def test_a_reorder_listing_a_foreign_clause_is_caught(tree, whole):
    merged, report = reduce_segments(
        tree,
        results(whole, [item(type="reorder_clauses", section="2", order=["2.1", "2.2", "3.1"])]),
    )
    assert merged == []
    assert "not children of" in reasons(report)


def test_an_out_of_range_table_is_caught(tree, whole):
    merged, report = reduce_segments(
        tree, results(whole, [item(type="update_cell", table=9, row=0, col=0, text="x")])
    )
    assert merged == []
    assert "out of range" in reasons(report)


# ---------------------------------------------------------------------------
# ordering and capping
# ---------------------------------------------------------------------------
def test_structural_actions_run_deletes_first_inserts_last(tree, whole):
    """Deletes first makes a doomed move fail loudly; inserts last stops anything
    resolving through a temporarily duplicated clause number."""
    merged, _ = reduce_segments(
        tree,
        results(
            whole,
            [
                item(id="A", type="insert_clause", after_clause="3.1", text="New."),
                item(id="B", type="move_clause", clause="4.2", after_clause="4.3"),
                item(id="C", type="delete_clause", clause="1.2"),
                item(
                    id="D",
                    type="replace_text",
                    clause="2.2",
                    find="thirty (30) days",
                    replace="45 days",
                ),
            ],
        ),
    )
    assert kinds(merged) == ["replace_text", "delete_clause", "move_clause", "insert_clause"]


def test_annotations_are_ordered_last(tree, whole):
    merged, _ = reduce_segments(
        tree,
        results(
            whole,
            [
                item(id="A", type="comment", clause="2.2", text="Check."),
                item(
                    id="B",
                    type="replace_text",
                    clause="2.2",
                    find="thirty (30) days",
                    replace="45 days",
                ),
            ],
        ),
    )
    assert kinds(merged) == ["replace_text", "comment"]


def test_the_cap_keeps_the_most_severe(tree, whole):
    merged, report = reduce_segments(
        tree,
        results(
            whole,
            [
                item(
                    id="A",
                    type="replace_text",
                    clause="2.2",
                    find="thirty (30) days",
                    replace="45 days",
                    severity="low",
                ),
                item(
                    id="B",
                    type="replace_text",
                    clause="3.2",
                    find="renews automatically",
                    replace="renews on notice",
                    severity="critical",
                ),
            ],
        ),
        max_actions=1,
    )
    assert len(merged) == 1 and merged[0]["severity"] == "critical"
    assert "cap" in reasons(report)


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------
def test_the_report_accounts_for_every_proposal(tree, whole):
    merged, report = reduce_segments(
        tree,
        results(
            whole,
            [
                item(
                    id="A",
                    type="replace_text",
                    clause="2.2",
                    find="thirty (30) days",
                    replace="45 days",
                ),
                item(
                    id="B",
                    type="replace_text",
                    clause="2.2",
                    find="thirty (30) days",
                    replace="45 days",
                ),
                item(id="C", type="delete_clause", clause="99.9"),
            ],
        ),
    )
    summary = report.to_dict()["summary"]
    assert summary["proposed"] == 3
    assert summary["kept"] == len(merged) == 1
    assert summary["dropped"] + summary["unresolved"] + summary["conflicts"] == 2


def test_a_skipped_segment_is_recorded(tree, whole):
    _, report = reduce_segments(
        tree, [SegmentResult(whole, [], status="skipped", detail="triage: skip", priority="skip")]
    )
    assert report.to_dict()["summary"]["skipped"] == 1


# ---------------------------------------------------------------------------
# verification is measured against the original, not against nothing
# ---------------------------------------------------------------------------
def test_pre_existing_dangling_references_do_not_fail_the_run(tmp_path, agreement_bytes):
    """A real contract cites other agreements and statutes. An absolute check
    fails on run one for reasons the redline had nothing to do with."""
    import docx

    from docx_redline import full_redline

    d = docx.Document(agreement_bytes)
    d.paragraphs[-1].insert_paragraph_before(
        "Nothing here limits Section 12 of the Master Services Agreement."
    )
    source = tmp_path / "with_foreign_reference.docx"
    d.save(str(source))

    result = full_redline(
        source,
        tmp_path / "out.docx",
        date="2026-01-01T00:00:00Z",
        actions=[
            {
                "id": "A",
                "type": "replace_text",
                "clause": "2.2",
                "find": "thirty (30) days",
                "replace": "forty-five (45) days",
                "rationale": "r",
                "severity": "low",
            }
        ],
    )
    assert result.ok, result.format()
    names = [name for name, _, _ in result.checks]
    assert "no cross-reference was broken" in names


def test_a_reference_this_redline_breaks_is_still_caught(tmp_path, agreement_bytes):
    from docx_redline import full_redline

    source = tmp_path / "base.docx"
    source.write_bytes(agreement_bytes.getvalue())
    # 2.3 is the last clause of its section, so nothing inherits its number and
    # the exhibit's "Sections 2.2 and 2.3" is genuinely orphaned.
    result = full_redline(
        source,
        tmp_path / "out.docx",
        date="2026-01-01T00:00:00Z",
        actions=[
            {
                "id": "A",
                "type": "delete_clause",
                "clause": "2.3",
                "rationale": "r",
                "severity": "low",
            }
        ],
    )
    check = {name: passed for name, passed, _ in result.checks}
    assert check["no cross-reference was broken"] is False
    assert not result.ok
