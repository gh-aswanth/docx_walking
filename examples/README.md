# examples

Every option in `docx_redline`, demonstrated in a runnable file. Each example is
standalone, runs offline in well under a second, prints what it did, and writes
any `.docx` it produces to `examples/output/`.

```bash
python examples/run_all.py          # run all 26, report pass/fail
python examples/run_all.py -v       # ...and show each one's output
python examples/run_all.py 12 13    # just these
python examples/12_edits_and_notes.py
```

`run_all.py` exits non-zero if any example fails, so it works as a CI gate. An
example that stops running is a README that has started lying.

## Layer 1 — `Redliner`

| | | Covers |
|---|---|---|
| 01 | [quickstart](01_quickstart.py) | the smallest useful redline |
| 02 | [redliner options](02_redliner_options.py) | `source` `author` `initials` `date` `track_changes` `scope` `include_tables` |
| 03 | [finding text](03_finding_text.py) | `find_paragraphs` `find_paragraph` `find_text` `text_of`; every filter, and why `Paragraph.text` is wrong |
| 04 | [insert and delete](04_insert_and_delete.py) | `insert_text` `insert_text_before/after` `append_text` `delete_text` `delete_matching` |
| 05 | [replace text](05_replace_text.py) | `count` `regex` backreferences `ignore_case` `insertion_first`; run boundaries; `set_paragraph_text` |
| 06 | [paragraphs](06_paragraphs.py) | `insert_paragraph_before/after` `copy_format` `style` `append_paragraph` `delete_paragraph(s)` `move_paragraph` `relocate_paragraph` |
| 07 | [tables](07_tables.py) | `tables` `insert_table_row` `delete_table_row` `delete_row` `set_cell_text` |
| 08 | [formatting](08_formatting.py) | every run and paragraph prop; `format_runs/matching/paragraph_text/paragraph`; `apply_style` vs `format_paragraph(style=)` |
| 09 | [comments](09_comments.py) | `add_comment` whole-paragraph, `runs=`, `author=`/`initials=`, commenting on a strikeout |
| 10 | [review](10_review_accept_reject.py) | `summary` `counts` `authors` `accept_all` `reject_all` `accept_file` `reject_file`; stacking authors |

## Layer 2 — `ParagraphIndex`

| | | Covers |
|---|---|---|
| 11 | [paragraph index](11_paragraph_index.py) | `ParagraphRef` fields, `clauses` `find` `paragraph` `render` `manifest` `fingerprint` `locate` `refresh` |
| 12 | [edits and notes](12_edits_and_notes.py) | every `RedlineEdit`/`ReviewNote` field, `occurrence`, `insertion_first`, span-anchored notes, `ApplyReport` |
| 13 | [rejections](13_rejections.py) | all six `Rejection` values, one at a time, and three ways to resolve an ambiguity |
| 14 | [fold](14_fold_matching.py) | what folds, the length invariant, why ligatures are left alone |
| 15 | [fingerprints](15_fingerprint_and_plans.py) | `fingerprint` on three input types, `verify_plan`, `StalePlanError` |
| 16 | [model output](16_model_output.py) | `validate_edits` `load_edits` `strict=`, every schema problem |

## Layer 3 — action items and the pipeline

| | | Covers |
|---|---|---|
| 17 | [action items](17_action_items.py) | `validate_actions` `apply_actions` `ActionPlanner`; `renumber` `strict` `explain`; `PlanReport` |
| 18 | [action vocabulary](18_action_vocabulary.py) | all 17 action types with every optional field, plus the two derived ones a model must not emit |
| 19 | [renumbering cascade](19_renumbering_cascade.py) | one move → nine consequences; dangling references; edited-then-moved clauses |
| 20 | [pipeline](20_pipeline_and_full_redline.py) | every stage on its own, `on_stage`, every `RedlinePipeline` and `full_redline` option |
| 21 | [reviewers](21_reviewers_and_chunked.py) | the registry, `propose(tree, brief)`, every `Claude`/`OpenAI`/`Chunked` option — all offline |

## Other surfaces

| | | Covers |
|---|---|---|
| 22 | [op plans](22_ops_plan.py) | all 13 op types, the shared keys, `validate`, `strict` |
| 23 | [document compare](23_document_compare.py) | `redline_files` `compare_documents` `similarity_floor`; accept == revised, reject == original |
| 24 | [structure](24_structure_and_segments.py) | `ClauseTree` `Clause` `outline` `render_outline` `iter_references` `detect_strategy` `iter_blocks` `render_document` `segment_document` `DocSegment` |
| 25 | [cli](25_cli.py) | every subcommand and flag, run as real subprocesses, with exit codes |
| 26 | [errors](26_errors.py) | the exception hierarchy and what raises which |

## Notes

- `_shared.py` holds the scaffolding (paths, `banner`, `fresh`, `save`). It is
  not part of the library.
- `data/` holds the fixtures: the sample contract and a 29-item plan covering
  every action type. `tests/conftest.py` reads the same two files, so a change
  to either shows up in the examples and the suite at once.
- Every example starts from an untouched copy of the sample contract.
- No example needs an API key. 21 constructs the model-backed reviewers and
  inspects them without ever calling one; 25 skips `doctor` for the same reason.
- Open anything in `examples/output/` with **Review → All Markup** to see the
  revisions the way a reviewer would.
