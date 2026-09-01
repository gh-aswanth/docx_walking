# 10 · Paragraph addressing

*How a model points at text, and how a wrong pointer is refused rather than guessed.*

---

## The problem this solves

[Clause renumbering](03-clause-renumbering.md) shows why clause numbers are the
right address for a lawyer. They are the wrong one for a machine: they move, the
renumbering pass rewrites them, and a document with no numbering has nothing to
address at all.

```mermaid
flowchart LR
    subgraph bad ["addressing by clause number"]
        B1["model reads 12.1"] --> B2["an earlier action<br/>inserts a section"]
        B2 --> B3["12.1 is now 13.1"]
        B3 --> B4["the edit lands<br/><b>somewhere else</b>"]
    end
    style B4 fill:#fce8e6,stroke:#ea4335
```

`ParagraphIndex` gives every `w:p` in scope a **stable integer id** in document
order, and pairs it with an **exact quoted span**. Two coordinates, both of
which the model can see in what it was given.

---

## Why a quote, and not an offset

```mermaid
flowchart TB
    Q{"the model says<br/>'change this'"}
    Q -->|"offset 159-175"| OFF["does not survive a reparse.<br/>Silently points at other text."]
    Q -->|"'thirty (30) days'"| QUOTE["survives. And when it stops matching,<br/><b>that is the signal</b> the document moved on."]

    style OFF fill:#fce8e6,stroke:#ea4335
    style QUOTE fill:#e6f4ea,stroke:#34a853
```

A stale offset fails silently. A stale quote fails loudly, which is the whole
difference.

---

## fold — matching what Word actually stored

A model quotes a phrase with straight quotes and a plain hyphen. Word stored
curly quotes and an en dash. Neither is wrong; they simply are not equal.

```mermaid
flowchart LR
    RAW["<b>in the document</b><br/>“twelve (12)–month”<br/><i>U+201C · U+2013 · U+201D</i>"] --> FOLD
    QUOTED["<b>from the model</b><br/>&quot;twelve (12)-month&quot;<br/><i>U+0022 · U+002D · U+0022</i>"] --> FOLD
    FOLD["fold()<br/><i>one char in, one char out</i>"] --> MATCH["both become<br/>&quot;twelve (12)-month&quot;<br/><b>they match</b>"]

    style MATCH fill:#e6f4ea,stroke:#34a853
    style FOLD fill:#e8f0fe,stroke:#4285f4
```

Every mapping is **one character to one character** — smart quotes, all six
dashes, every exotic space, tabs. That is what makes an offset computed on the
folded string valid on the raw string it came from, so the result can be handed
straight to `oxml/edits.py`.

NFKC is applied one character at a time and kept only when it maps 1 → 1: `Ａ`
folds to `A`, while the `ﬁ` ligature is left alone rather than expanding to two
characters and shifting every offset after it.

---

## Locate everything, then apply — right to left

```mermaid
flowchart TB
    IN[/"edits and notes"/] --> LOC["<b>locate</b> every one<br/><i>against a snapshot of the document</i>"]
    LOC --> ANY{"any refused?"}
    ANY -->|yes| REPORT["record it.<br/><b>Nothing has been written yet.</b>"]
    ANY --> APPLY["<b>apply</b>, right to left"]
    APPLY --> WHY["so no applied edit<br/>invalidates a pending offset"]

    style REPORT fill:#fef7e0,stroke:#f9ab00
    style APPLY fill:#e6f4ea,stroke:#34a853
```

Locating and applying must stay separate passes. Locate lazily and the second
edit to touch a paragraph sees XML the first one already rewrote — its text now
sits in `w:delText` — and the miss gets misdiagnosed as a parse problem rather
than the collision it is.

A plan that is half wrong therefore cannot leave the document half edited by the
time it is found out.

---

## Six ways to be refused

```mermaid
flowchart TB
    T(["an edit arrives"]) --> P{"para_id in range?"}
    P -->|no| R1["PARAGRAPH_NOT_FOUND<br/><i>the detail names the valid range</i>"]
    P --> E{"target non-empty?"}
    E -->|no| R2["EMPTY_TARGET"]
    E --> F{"quote found?"}
    F -->|"only inside a w:del"| R3["TARGET_ALREADY_STRUCK"]
    F -->|no| R4["TARGET_NOT_FOUND<br/><i>never fuzzy-matched</i>"]
    F --> A{"found more than once,<br/>and under 25 chars?"}
    A -->|yes| R5["TARGET_AMBIGUOUS<br/><i>quote more, or set occurrence</i>"]
    A --> C{"span already claimed<br/>by an earlier edit?"}
    C -->|yes| R6["SPAN_CONFLICT<br/><i>send both to reconciliation</i>"]
    C --> OK["apply"]

    style OK fill:#e6f4ea,stroke:#34a853
    style R4 fill:#fce8e6,stroke:#ea4335
    style R5 fill:#fef7e0,stroke:#f9ab00
    style R6 fill:#fef7e0,stroke:#f9ab00
```

`TARGET_NOT_FOUND` is the important one. The engine will not fuzzy-match a quote
that nearly fits — a near miss is far more likely to be a model quoting from
memory than a document that shifted by a word.

---

## Notes are anchors, not rewrites

A `ReviewNote` becomes a Word comment, so it cannot invalidate anyone's offsets.
That buys two behaviours edits do not get:

```mermaid
flowchart LR
    N1["a note never<br/><b>claims</b> a span"] --> N2["so a note and an edit<br/>may target the same words"]
    N3["a note is re-located<br/>against the <b>finished</b> text"] --> N4["and if an edit struck those words,<br/>it anchors at the paragraph<br/>and records why"]

    style N2 fill:#e6f4ea,stroke:#34a853
    style N4 fill:#e6f4ea,stroke:#34a853
```

Commenting *on* a strikeout is usually the point, so `TARGET_ALREADY_STRUCK`
refuses an edit but is only a fallback for a note.

---

## Binding a plan to a document version

The model may take minutes to answer. The document may not have waited.

```mermaid
flowchart LR
    A["fingerprint()<br/><i>sha256 of the text</i>"] --> B["...review happens..."]
    B --> C{"verify_plan()"}
    C -->|"same"| D["apply"]
    C -->|"different"| E["<b>StalePlanError</b><br/><i>re-render and re-review</i>"]

    style D fill:#e6f4ea,stroke:#34a853
    style E fill:#fce8e6,stroke:#ea4335
```

It hashes text only, so re-attributing the author or re-stamping the date does
not invalidate a plan. This is the guard that stops a v3 redline landing on a
v4 document.

---

## What the model is given

`render()` is the cacheable prefix. Every line starts with the id an edit
addresses, so the model can only ever point at a paragraph that exists:

```
<<clause 3.2>>
[19] 3.2  Invoicing. Provider shall invoice Customer annually in advance ...
```

Ids are positions in `rl.paragraphs()`. They survive every text edit, comment
and formatting change; a structural pass that inserts or deletes a paragraph
invalidates them, which is what `refresh()` and a new `fingerprint()` are for.

---

## Where this sits

| | Addresses by | Verifies before writing |
|---|---|---|
| `Redliner` | text, paragraph object, table index | no |
| **`ParagraphIndex`** | **integer id + quoted span** | **yes — every edit is located first** |
| `ActionPlanner` | clause number (`"12.1"`) | schema first, then clause resolution |

Use this layer when a model quotes spans back at you and may be wrong. Use
[the action pipeline](04-action-pipeline.md) when a model is restructuring the
document and the numbering has to follow.

---

## Where to look

| | |
|---|---|
| `editing/paragraphs.py` | `ParagraphIndex`, `fold`, `Rejection`, `fingerprint`, `verify_plan` |
| `oxml/textmap.py` | the flat coordinate space the offsets live in |
| `tests/test_paragraphs.py` | one test per rejection, and the length invariant of `fold` |
| [`examples/13_rejections.py`](../examples/13_rejections.py) | every refusal, triggered one at a time |

**Back to:** [index](README.md)
