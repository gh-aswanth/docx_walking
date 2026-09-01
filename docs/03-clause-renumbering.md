# 3 · Clause renumbering

*Why asking for one move rewrites 16 numbers and 5 cross-references.*

---

## The problem

Contracts number clauses in the **body text**, not with Word's auto-numbering.
So a structural change is never one edit:

```mermaid
flowchart LR
    ASK["<b>you ask for</b><br/>move 12.1 after 4.1"] ==> GET["<b>what must happen</b>"]
    GET --> G1["12.1 takes a new number<br/>at its destination"]
    GET --> G2["its new neighbours<br/>shift down"]
    GET --> G3["the clauses it left<br/>close ranks"]
    GET --> G4["every 'as set out in<br/>Section X.Y' follows"]

    style ASK fill:#e8f0fe,stroke:#4285f4
    style GET fill:#fef7e0,stroke:#f9ab00
```

The reviewer only says *what*. The engine derives the rest — and a model must
never emit its own renumbering, or it double-applies. `renumber_clause` and
`update_cross_reference` are **derived actions**: `validate_actions` rejects them
if a model supplies one.

---

## A real cascade

`{"type": "move_clause", "clause": "12.1", "after_clause": "4.1"}` produces:

```text
  12.1  ->  4.2     Governing Law           ← the clause that moved
   4.2  ->  4.3     Auto-Renewal            ← destination siblings shift down
   4.3  ->  4.4     Termination for Cause
   4.4  ->  4.5     Effect of Termination
  12.2  ->  12.1    Assignment              ← source siblings close ranks
  12.3  ->  12.2    Force Majeure
  12.4  ->  12.3    Notices
  12.5  ->  12.4    Entire Agreement
  12.6  ->  12.5    Severability

  Section 4.2 -> Section 4.3   in Exhibit A
```

---

## How it works: derive, never increment

```mermaid
sequenceDiagram
    participant P as ActionPlanner
    participant T as ClauseTree
    participant D as document

    P->>T: snapshot()
    Note over P,T: freeze today's numbering<br/>BEFORE anything moves
    P->>D: apply content actions
    P->>D: apply structural actions
    Note over P,D: labels are untouched —<br/>numbers still read as they did
    P->>P: finalize()
    P->>T: reload()
    T->>T: renumber() — derive 1..n from position
    T-->>P: relabelled + mapping
    P->>D: rewrite each changed label (tracked)
    P->>D: rewrite each cross-reference (tracked)
```

**One pass, at the very end.** That is what lets a move that shifts two separate
sibling groups — plus an insert and a delete in the same run — produce a single
coherent numbering instead of several passes fighting.

---

## Rules the cascade follows

```mermaid
flowchart TB
    R1["struck or moved-away paragraphs<br/>are excluded<br/><i>number it as it will read once accepted</i>"]
    R2["references found across the whole document<br/><i>exhibits, tables, headers, footers, notes</i>"]
    R3["lists handled: 'Sections 10.2 and 10.3'<br/>yields two separate hits"]
    R4["a reference to a <b>deleted</b> clause is<br/>reported, never silently remapped"]
    R5["renumbering a clause is itself tracked —<br/>unless the clause is one this run inserted"]
```

That last one matters: editing inside a `w:ins` would show reviewers a
strikeout on text the original document never contained.

---

## What "one structural action" really touches

```mermaid
flowchart TB
    subgraph before ["before"]
        direction TB
        B4["§4 &nbsp; 4.1 4.2 4.3 4.4"]
        B12["§12 &nbsp; 12.1 12.2 12.3 12.4 12.5 12.6"]
    end
    subgraph after ["after"]
        direction TB
        A4["§4 &nbsp; 4.1 <b>4.2</b> 4.3 4.4 4.5"]
        A12["§12 &nbsp; 12.1 12.2 12.3 12.4 12.5"]
    end
    before ==>|"move 12.1 → after 4.1"| after
    after --> REFS["+ 1 cross-reference in Exhibit A"]

    style A4 fill:#e6f4ea,stroke:#34a853
    style A12 fill:#fef7e0,stroke:#f9ab00
```

---

## Reordering a section

`reorder_clauses` restates a section's sequence. Only the clauses that genuinely
have to move are moved — the longest run already in relative order stays put.

```mermaid
flowchart LR
    IN["[A, B, C]<br/>order: [C, A, B]"] --> LIS["longest increasing run<br/>= A, B"]
    LIS --> OUT["<b>1 move revision</b>, not 3<br/><i>C jumps; A and B stay</i>"]

    style OUT fill:#e6f4ea,stroke:#34a853
```

Clauses the request does not mention keep their exact slot, so an unlisted
clause never drifts to the end as a side effect.

---

## Blast radius — worth knowing

An `insert_section` near the front relabels **every** following section and
every clause beneath it, plus every cross-reference. On a 300-page contract that
is thousands of tracked changes from one action.

```mermaid
flowchart LR
    ONE["insert_section<br/>after §2"] --> MANY["§3…§300 renumber<br/>+ all their sub-clauses<br/>+ every reference"]
    style MANY fill:#fce8e6,stroke:#ea4335
```

Turn it off with `--no-renumber` when you want the literal actions and nothing
else. The numbering checks are skipped too, since inconsistency is then expected.

---

## Where to look

| | |
|---|---|
| `structure/clauses.py` | `ClauseTree.renumber`, `LabelSnapshot`, `iter_references`, `collect_reference_edits` |
| `planning/actions.py` | `ActionPlanner._renumber`, `_rewrite_label`, `_rewrite_reference` |

**Next:** [The action pipeline →](04-action-pipeline.md)
