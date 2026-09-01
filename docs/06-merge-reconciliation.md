# 6 · Merge & reconciliation

*Turning proposals from segments that never saw each other into one plan.*

---

## Why this stage is adversarial towards its own input

Each segment is reviewed in isolation. Their proposals arrive with colliding
ids, overlapping edits and contradictory structural intentions — and applying
the raw union **does not fail loudly**:

```mermaid
flowchart LR
    NAIVE["apply the union<br/>as it arrives"] --> OUT["<b>status: applied</b> on everything<br/><b>result.ok: true</b>"]
    OUT --> REAL["…and a document that is quietly wrong"]

    style OUT fill:#fef7e0,stroke:#f9ab00
    style REAL fill:#fce8e6,stroke:#ea4335
```

So the merge assumes its input is wrong until each item proves otherwise, and
records a reason for everything it discards.

---

## The pipeline

```mermaid
flowchart TB
    IN[/"proposals from N segments"/] --> S1
    S1["<b>1 · stage</b><br/>drop what a segment could not claim"]
    S2["<b>2 · dedupe</b><br/>identical edits collapse"]
    S3["<b>3 · conflicts</b><br/>one winner per contested target"]
    S4["<b>4 · pre-flight</b><br/>resolve against the untouched document"]
    S5["<b>5 · order</b><br/>content → structural → annotations"]
    S6["<b>6 · re-id</b><br/>AI-0001…, provenance kept"]
    S7["<b>7 · cap</b><br/>optional, most severe first"]
    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7
    S7 --> OUT[/"one plan · validate_actions == []"/]
    S1 & S2 & S3 & S4 & S7 -.-> REP[["MergeReport<br/><i>every discard, with a reason</i>"]]

    style OUT fill:#e6f4ea,stroke:#34a853
    style REP fill:#e8f0fe,stroke:#4285f4
```

---

## 1 · Staging — what a segment may claim

```mermaid
flowchart TB
    ITEM["an item from segment S07"] --> A{"is its type allowed?<br/><i>no clause numbering ⇒<br/>no structural actions</i>"}
    A -->|no| DROP1["dropped"]
    A -->|yes| B{"does it target a clause<br/>inside S07?"}
    B -->|"targets another segment"| DROP2["dropped —<br/>'outside this segment'"]
    B -->|"targets nothing that exists"| PASS["let it through —<br/><i>pre-flight will say why</i>"]
    B -->|yes| PASS

    style DROP1 fill:#fce8e6,stroke:#ea4335
    style DROP2 fill:#fce8e6,stroke:#ea4335
```

Ownership is what makes read-only boundary context safe. It deliberately does
**not** reject a clause number that exists nowhere — saying "this clause does
not exist" is more useful than "it belongs to another segment".

---

## 2 · Dedupe on the whole item

```mermaid
flowchart LR
    BAD["key = (type, clause, find, replace)"] --> BADX["❌ <code>find</code> and <code>replace</code> are absent on<br/>every insert_clause / move_clause /<br/>reorder_clauses / rewrite_clause —<br/>this collapses them all into one"]
    GOOD["key = the whole item<br/>minus id · rationale · severity"] --> GOODX["✅ two items are the same edit only<br/>when every field that matters agrees"]

    style BADX fill:#fce8e6,stroke:#ea4335
    style GOODX fill:#e6f4ea,stroke:#34a853
```

---

## 3 · Conflicts — one winner, most severe first

```mermaid
flowchart TB
    R1["<b>delete beats everything</b><br/>on the same clause or any descendant"]
    R2["<b>one structural action per label</b><br/>across all 7 target keys"]
    R3["<b>rewrite_clause suppresses</b><br/>piecemeal edits to that clause"]
    R4["<b>two replace_text</b> on one clause<br/>drop only on genuine overlap"]
    R5["<b>one reorder per section</b>"]
    R6["<b>one insert_text per anchor</b><br/><i>two at one anchor apply in reverse order</i>"]
```

Items are considered in severity order, so the more serious proposal wins the
target and the loser is recorded with the rule that displaced it.

> Disjoint edits to one clause **both survive**. Only genuine intersection is a
> conflict; dropping non-overlapping edits would lose real review.

---

## 4 · Pre-flight — resolve before anything is opened

```mermaid
flowchart TB
    ITEM["item"] --> C1{"every clause / section /<br/>anchor label exists?"}
    C1 -->|no| U1["unresolved:<br/>'99.9 is not a clause'"]
    C1 -->|yes| C2{"does <code>find</code> occur<br/>in its target?"}
    C2 -->|"0 times"| U2["unresolved:<br/>'does not occur in clause 2.2'"]
    C2 -->|"more than once, unscoped"| U3["unresolved:<br/>'ambiguous'"]
    C2 -->|yes| C3{"reorder lists only<br/>that section's children?<br/>table / row / col in range?"}
    C3 -->|no| U4["unresolved"]
    C3 -->|yes| KEEP["kept"]

    style KEEP fill:#e6f4ea,stroke:#34a853
    style U1 fill:#fce8e6,stroke:#ea4335
    style U2 fill:#fce8e6,stroke:#ea4335
    style U3 fill:#fce8e6,stroke:#ea4335
    style U4 fill:#fce8e6,stroke:#ea4335
```

This turns *"200 failed actions halfway through applying a 500-item plan"* into
*"200 items explained before the document was touched"*.

---

## 5 · Ordering

```mermaid
flowchart LR
    CONTENT["content"] --> STRUCT["structural"] --> ANNOT["annotations"]

    subgraph inner ["structural, in dependency order"]
        direction LR
        D1["delete_section"] --> D2["delete_clause"] --> M1["move_section"] --> M2["move_clause"] --> RE["reorder_clauses"] --> I1["insert_section"] --> I2["insert_clause"]
    end
    STRUCT -.-> inner
```

Two reasons this exact order:

- **Deletes first** — a move into a subtree that gets deleted becomes a loud
  `ClauseError` instead of a clause silently vanishing.
- **Inserts last** — a new clause borrows its neighbour's number until
  renumbering runs, so nothing else should be resolving while a duplicate exists.

---

## 6 · Re-id — the failure that stops the run dead

```mermaid
flowchart LR
    S1["segment 1<br/>AI-001, AI-002…"] --> M
    S2["segment 2<br/><b>AI-001</b>, AI-002…"] --> M
    M{"merge"} -->|"without re-id"| BOOM["<b>validate_actions</b>: duplicate id<br/>→ ActionPlanner <b>raises</b><br/>→ the entire run is discarded"]
    M -->|"with re-id"| OK["AI-0001 … AI-0247<br/><i>note: 'S07' keeps the provenance</i>"]

    style BOOM fill:#fce8e6,stroke:#ea4335
    style OK fill:#e6f4ea,stroke:#34a853
```

Every reviewer restarts its numbering at `AI-0001`, so this is certain, not
theoretical. It is also the only conflict the rest of the system catches on its
own — and it catches it by refusing to run at all.

---

## The report

```json
{
  "summary": {
    "segments": 12, "reviewed": 9, "skipped": 3,
    "proposed": 214, "kept": 176,
    "dropped": 21, "conflicts": 9, "unresolved": 8
  },
  "segments":   [ { "id": "S07", "status": "ok", "items": 23, … } ],
  "triage":     { "notes": "…", "priorities": { "S07": "deep" } },
  "provenance": { "AI-0042": { "segment": "S07", "original_id": "AI-003" } },
  "dropped":    [ { "reason": "identical to S06/AI-011", … } ],
  "conflicts":  [ { "kept": "S07/AI-003", "rule": "delete beats…", … } ],
  "unresolved": [ { "reason": "find='…' does not occur in clause 4.2", … } ]
}
```

Every proposal is accounted for: `kept + dropped + conflicts + unresolved`
equals `proposed`. Write it with `--merge-report merge.json`.

---

## Where to look

| | |
|---|---|
| `merge.py` | `reduce_segments` and each stage above |
| `actions.py` | `validate_actions`, `STRUCTURAL_ACTIONS`, `ANNOTATION_ACTIONS` |

**Next:** [Verification →](07-verification.md)
