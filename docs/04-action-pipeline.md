# 4 · The action pipeline

*What `full_redline` does, stage by stage.*

---

## The whole run

```mermaid
flowchart TB
    S1["<b>extract</b><br/><i>parse into a clause tree + block walk</i>"]
    S2["<b>propose</b><br/><i>a reviewer, a JSON file, or inline items</i>"]
    S3["<b>validate</b><br/><i>schema-check before the document is opened</i>"]
    S4["<b>compare</b><br/><i>diff a second .docx in — optional</i>"]
    S5["<b>plan</b><br/><i>content → structural → annotations</i>"]
    S6["<b>renumber</b><br/><i>labels + cross-references, once</i>"]
    S7["<b>apply</b><br/><i>count what was written</i>"]
    S8["<b>verify</b><br/><i>accept ⇄ reject round trip</i>"]
    S9["<b>report</b><br/><i>docx + JSON</i>"]

    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7 --> S8 --> S9

    style S3 fill:#fef7e0,stroke:#f9ab00
    style S8 fill:#fce8e6,stroke:#ea4335
    style S9 fill:#e6f4ea,stroke:#34a853
```

Any stage or check failing makes `result.ok` false, and the entry point exits
non-zero — so it drops into CI as-is.

---

## Three independent sources of edits

```mermaid
flowchart LR
    A["<b>revised.docx</b><br/>Word-Compare style diff"] --> M
    B["<b>action items</b><br/>list, JSON file, or a reviewer"] --> M
    C["<b>comments</b><br/>clause or quoted phrase"] --> M
    M{{"one document<br/>one planner<br/>one renumbering pass"}}
```

Any subset works. Passing none raises rather than writing an unchanged file.

---

## Order is the substance of it

```mermaid
sequenceDiagram
    autonumber
    participant F as full_redline
    participant P as ActionPlanner
    participant D as document

    F->>P: construct (renumber deferred)
    Note over P: baseline snapshot taken HERE —<br/>before anything moves
    F->>D: compare_into(revised)
    Note over F,D: compare first, so actions address<br/>the document the diff produced
    F->>P: run(action items + comments)
    P->>D: content actions
    P->>D: structural actions
    P->>D: comments
    Note over P,D: comments last — they anchor to<br/>finished text, not to a moved paragraph
    F->>P: finalize()
    P->>D: renumber + cross-references
    Note over P,D: once, over the combined result
```

Get this order wrong and a compare that inserts a clause fights an action that
moves one, producing two inconsistent numberings.

---

## The action vocabulary

**17 types, 33 fields.** Structural ones trigger the renumbering cascade.

```mermaid
flowchart TB
    subgraph content ["content — no structural consequence"]
        direction LR
        C1["replace_text"] ~~~ C2["insert_text"] ~~~ C3["delete_text"] ~~~ C4["rewrite_clause"]
        C5["insert_row"] ~~~ C6["delete_row"] ~~~ C7["update_cell"]
        C8["format_text"] ~~~ C9["format_clause"]
    end
    subgraph structural ["structural — renumbers"]
        direction LR
        S1["insert_clause"] ~~~ S2["delete_clause"] ~~~ S3["move_clause"] ~~~ S4["reorder_clauses"]
        S5["insert_section"] ~~~ S6["delete_section"] ~~~ S7["move_section"]
    end
    subgraph annotation ["annotation — runs last"]
        A1["comment"]
    end
    subgraph derived ["derived — the engine's, never a model's"]
        direction LR
        D1["renumber_clause"] ~~~ D2["update_cross_reference"]
    end

    style structural fill:#fef7e0
    style derived fill:#fce8e6
```

Every action also takes `id`, `rationale` and `severity`
(`low` / `medium` / `high` / `critical`).

---

## An action item

```json
{
  "id": "AI-011",
  "type": "move_clause",
  "clause": "12.1",
  "after_clause": "4.1",
  "rationale": "Governing law belongs with the term provisions.",
  "severity": "medium"
}
```

Adding `clause` to a *text* action scopes the search, so a phrase appearing in
five places is unambiguous.

---

## Rationales reach the document

Each applied action's `rationale` is written into the `.docx` as a Word comment,
anchored on the paragraph it actually touched.

```mermaid
flowchart LR
    ITEM["action item<br/><i>rationale + severity</i>"] --> APPLIED{"applied?"}
    APPLIED -->|no| SKIP["not annotated"]
    APPLIED -->|yes| ANCHOR["find a live paragraph<br/><i>visible runs preferred;<br/>a strikeout still counts</i>"]
    ANCHOR --> CMT["<b>[AI-011 · medium]</b><br/>Governing law belongs with…"]

    style CMT fill:#e6f4ea,stroke:#34a853
```

It runs **after** renumbering, so a rationale never points at a paragraph a later
stage moved or renumbered away. Turn it off with `explain=False` / `--no-explain`.

---

## Running it

```bash
# everything at once
python -m docx_redline full contract.docx -o out.docx \
    --actions plan.json \
    --revised counterparty.docx \
    --comment "10.2=Confirm the cap with finance." \
    --report report.json

# or let a model write the plan
python -m docx_redline full contract.docx -o out.docx --reviewer claude
```

```python
from docx_redline import full_redline

result = full_redline(
    "contract.docx",
    "out.docx",
    revised="counterparty.docx",  # optional
    actions="plan.json",  # or a list, or reviewer=…
    comments=[{"clause": "10.2", "text": "Confirm with finance."}],
    report_path="report.json",
)
assert result.ok
```

Exit codes: `0` all checks passed · `1` a stage or check failed · `2` bad input.

---

## What a run looks like

```text
  [ok ] extract    12 sections, 54 clauses, 92 paragraphs, 2 tables
  [ok ] propose    loaded 29 action items from action_items.json
  [ok ] validate   schema clean
  [ok ] plan       29/29 actions applied
  [ok ] renumber   39 clause number(s) rewritten, 5 cross-reference(s) updated
  [ok ] apply      168 tracked changes written, 29 comment(s) attached
  [ok ] verify     7/7 checks passed
  [ok ] report     wrote out.docx
```

---

## Where to look

| | |
|---|---|
| `pipeline.py` | `RedlinePipeline`, `full_redline`, the stage methods |
| `actions.py` | `ACTION_SCHEMA`, `validate_actions`, `ActionPlanner` |
| `agent.py` | reviewers and the action-item schema |

**Next:** [Chunked review →](05-chunked-review.md)
