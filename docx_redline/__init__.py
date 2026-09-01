# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2026 Aswanth B S

"""Production-grade tracked changes (redlines) for ``.docx`` files.

Two entry points:

* :class:`~docx_redline.editing.redline.Redliner` -- targeted, scripted edits
  (insert / delete / replace / update / move / table rows / formatting).
* :func:`~docx_redline.compare.redline_files` -- diff two documents into a
  single Word-compatible redline, like Word's *Compare*.

Both emit real OOXML revision markup (``w:ins``, ``w:del``, ``w:rPrChange``,
...) so the result opens in Word, LibreOffice and Google Docs with a working
Accept/Reject UI.
"""

from .editing.compare import CompareStats, compare_documents, redline_files
from .editing.paragraphs import (
    ApplyReport,
    EditResult,
    ParagraphIndex,
    ParagraphRef,
    RedlineEdit,
    Rejection,
    ReviewNote,
    fingerprint,
    fold,
    load_edits,
    validate_edits,
    verify_plan,
)
from .editing.redline import Match, Redliner
from .editing.review import Revision, RevisionSummary, accept_all, reject_all, summarize
from .errors import ClauseError, RedlineError, StalePlanError
from .oxml.diffing import TextOp, diff_ops
from .oxml.revisions import Author, RevisionContext, RevisionIds
from .planning.actions import ActionPlanner, PlanReport, apply_actions, validate_actions
from .planning.agent import (
    ClaudeReviewer,
    OpenAIReviewer,
    Proposal,
    RedlineCredentialsError,
    RuleBasedReviewer,
    default_model_for,
    get_reviewer,
    load_proposal,
)
from .planning.chunked import ChunkedReviewer, SegmentProgress, build_index
from .planning.merge import MergeReport, SegmentResult, reduce_segments
from .planning.pipeline import PipelineResult, RedlinePipeline, full_redline
from .structure.clauses import Clause, ClauseTree, iter_references, outline, render_outline
from .structure.segments import (
    Block,
    DocSegment,
    detect_strategy,
    iter_blocks,
    render_document,
    segment_document,
)

__all__ = [  # noqa: RUF022 -- grouped by layer, not alphabetically
    "Redliner",
    "RedlineError",
    "ClauseError",
    "StalePlanError",
    "Match",
    # stable paragraph addressing & plan verification
    "ParagraphIndex",
    "ParagraphRef",
    "RedlineEdit",
    "ReviewNote",
    "EditResult",
    "ApplyReport",
    "Rejection",
    "fold",
    "fingerprint",
    "verify_plan",
    "load_edits",
    "validate_edits",
    # clause structure & renumbering
    "Clause",
    "ClauseTree",
    "iter_references",
    "outline",
    "render_outline",
    # whole-document view
    "Block",
    "DocSegment",
    "detect_strategy",
    "iter_blocks",
    "render_document",
    "segment_document",
    # action items & pipeline
    "ActionPlanner",
    "PlanReport",
    "apply_actions",
    "validate_actions",
    "RedlinePipeline",
    "PipelineResult",
    "full_redline",
    "Proposal",
    "ClaudeReviewer",
    "OpenAIReviewer",
    "ChunkedReviewer",
    "SegmentProgress",
    "build_index",
    "MergeReport",
    "SegmentResult",
    "reduce_segments",
    "RedlineCredentialsError",
    "RuleBasedReviewer",
    "get_reviewer",
    "default_model_for",
    "load_proposal",
    "compare_documents",
    "redline_files",
    "CompareStats",
    "accept_all",
    "reject_all",
    "summarize",
    "Revision",
    "RevisionSummary",
    "Author",
    "RevisionContext",
    "RevisionIds",
    "diff_ops",
    "TextOp",
    "accept_file",
    "reject_file",
]

__version__ = "1.0.0"


def accept_file(source, output):
    """Accept every tracked change in ``source`` and write ``output``."""
    rl = Redliner(source, track_changes=False)
    rl.accept_all()
    return rl.save(output)


def reject_file(source, output):
    """Reject every tracked change in ``source`` and write ``output``."""
    rl = Redliner(source, track_changes=False)
    rl.reject_all()
    return rl.save(output)
