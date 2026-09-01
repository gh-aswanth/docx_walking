# docx-redline — how it works

Ten short documents, one per workflow. Each is a diagram plus the few facts you
need to read it. Start here, then follow whichever thread you care about.

Want to see the output rather than read about it? The README has a
[gallery of rendered redlines](../README.md#what-it-produces), and
[`examples/`](../examples/) has 26 runnable files covering every option.

| | Workflow | Read it when you want to know |
|---|---|---|
| 1 | [Tracked changes](01-tracked-changes.md) | How one edit becomes Word revision markup |
| 2 | [Document structure](02-document-structure.md) | How the document is read and shown to a model |
| 3 | [Clause renumbering](03-clause-renumbering.md) | Why moving 12.1 rewrites 16 numbers and 5 references |
| 4 | [The action pipeline](04-action-pipeline.md) | What `full_redline` actually does, stage by stage |
| 5 | [Chunked review](05-chunked-review.md) | How a 300-page contract is reviewed |
| 6 | [Merge & reconciliation](06-merge-reconciliation.md) | How conflicting proposals become one plan |
| 7 | [Verification](07-verification.md) | How the result is proven correct |
| 8 | [Document compare](08-document-compare.md) | Diffing two `.docx` files into one redline |
| 9 | [Failure modes](09-failure-modes.md) | What goes wrong, and where it is caught |
| 10 | [Paragraph addressing](10-paragraph-addressing.md) | How a model points at text, and how a wrong pointer is refused |

---

## The system in one picture

```mermaid
flowchart TB
    subgraph input [" "]
        DOC[["contract.docx"]]
        BRIEF["review brief<br/>or action_items.json"]
        REV[["revised.docx<br/><i>optional</i>"]]
    end

    DOC --> STRUCT
    STRUCT["<b>structure</b><br/>structure/segments.py<br/><i>read the whole document</i>"] --> REVIEWER

    subgraph propose ["propose — where action items come from"]
        REVIEWER{"reviewer"}
        REVIEWER -->|rules| RULES["RuleBasedReviewer<br/><i>offline, deterministic</i>"]
        REVIEWER -->|claude / openai| ONE["single call<br/><i>whole document</i>"]
        REVIEWER -->|chunked| MANY["segment → triage →<br/>parallel map → merge"]
    end

    BRIEF --> REVIEWER
    RULES --> ITEMS
    ONE --> ITEMS
    MANY --> ITEMS
    ITEMS[/"action items<br/>17 types, 33 fields"/]

    ITEMS --> PLAN
    REV -.-> PLAN
    subgraph apply ["apply — one planner, one pass"]
        PLAN["<b>ActionPlanner</b><br/>planning/actions.py"] --> EDITS["tracked changes<br/>oxml/edits.py · editing/redline.py"]
        EDITS --> RENUM["<b>renumber</b><br/>structure/clauses.py<br/><i>labels + cross-references</i>"]
    end

    RENUM --> VERIFY["<b>verify</b><br/>accept ⇄ reject round trip"]
    VERIFY --> OUT[["redlined.docx"]]
    VERIFY --> REPORT[["report.json"]]

    style DOC fill:#e8f0fe,stroke:#4285f4
    style REV fill:#e8f0fe,stroke:#4285f4
    style OUT fill:#e6f4ea,stroke:#34a853
    style REPORT fill:#e6f4ea,stroke:#34a853
    style ITEMS fill:#fef7e0,stroke:#f9ab00
    style VERIFY fill:#fce8e6,stroke:#ea4335
```

---

## Three layers, pick the one you need

```mermaid
flowchart LR
    subgraph l1 ["1 — you know the paragraphs"]
        direction TB
        A1["Redliner"] --> A2["replace_text()<br/>delete_paragraph()<br/>insert_table_row()"]
    end
    subgraph l2 ["2 — a model quotes spans, and may be wrong"]
        direction TB
        B1["ParagraphIndex"] --> B2["RedlineEdit(19, 'thirty (30) days', ...)<br/><i>located before anything is written</i>"]
    end
    subgraph l3 ["3 — a model restructures the document"]
        direction TB
        C1["full_redline()"] --> C2["action items<br/>clause: '12.1'"]
        C2 --> C3["renumbering<br/>cross-references<br/>verification"]
    end
    l1 -.->|"is built on"| l2 -.->|"is built on"| l3
```

|  | `Redliner` | `ParagraphIndex` | `full_redline` |
|---|---|---|---|
| Addresses content by | text, paragraph, table index | integer id + quoted span | clause number (`"12.1"`) |
| Knows about numbering | no | reads it, does not rewrite it | yes — renumbers and repoints references |
| Verifies before writing | no | **yes** | schema, then clause resolution |
| Input | method calls | `RedlineEdit` / `ReviewNote`, or model JSON | action items from a reviewer or a file |
| Use when | you know exactly what to edit | something else is deciding, and may be wrong | something else is restructuring |
| Read | [1](01-tracked-changes.md) | [10](10-paragraph-addressing.md) | [4](04-action-pipeline.md) |

---

## Where the code lives

Four subpackages, strictly layered — each may import downward and never up, and
a test asserts it.

```
oxml  ->  structure  ->  editing  ->  planning  ->  cli
```

```
docx_redline/
  errors.py                   shared exception hierarchy
  cli.py                      command line front end

  oxml/                       OOXML plumbing — knows nothing about clauses
    ns.py elements.py           namespaces, element construction, schema order
    revisions.py                author, timestamp, unique w:id allocation
    textmap.py                  flat character map over a paragraph; run splitting
    edits.py                    the primitives: w:ins / w:del / ¶-marks / rows
    diffing.py                  word-level diff

  structure/                  reading the document — never writes a revision
    clauses.py                  clause tree, renumbering, cross-references
    segments.py                 whole-document view: detection, rendering, segmentation

  editing/                    applying edits — everything here writes revisions
    redline.py                  Redliner — the public low-level API
    review.py                   accept / reject / summarise
    compare.py                  document-vs-document redline
    ops.py                      declarative JSON edit plans
    paragraphs.py               paragraph ids, folded matching, plan fingerprints

  planning/                   deciding edits — what to change, not how
    actions.py                  action vocabulary + the planner
    merge.py                    reconciling proposals from independent segments
    agent.py                    reviewers: Claude, OpenAI, offline rules
    chunked.py                  long documents: index, triage, parallel map, cache
    pipeline.py                 the staged pipeline and full_redline
```

**350 tests** in `tests/`, **26 runnable examples** in `examples/`. The invariant
nearly all of them lean on:

> `accept(redline)` is the intended new document.
> `reject(redline)` is the original, exactly.
