# 1 · Tracked changes

*How one edit becomes Word revision markup.*

Everything else in this repo eventually calls into here. The goal is that Word,
LibreOffice and Google Docs all show the change in their native review pane with
a working Accept/Reject button — not strikethrough formatting that merely looks
like a redline.

---

## The problem: Word does not store text as text

A paragraph is a sequence of *runs*, split wherever formatting changes. The
phrase you want to edit rarely lines up with them.

```mermaid
flowchart LR
    subgraph para ["w:p — 'Payment is due within thirty (30) days of the invoice date.'"]
        direction LR
        R1["w:r<br/>'Payment is due within '"]
        R2["<b>w:r</b><br/><b>'thirty (30) days'</b><br/><i>bold</i>"]
        R3["w:r<br/>' of the invoice date.'"]
    end
```

To replace `within thirty (30) days of` you must edit across three runs with
three different formats.

---

## The fix: a flat character map, then split at the boundaries

```mermaid
flowchart TB
    A["ParagraphText(p)<br/><i>flat text, ignoring already-deleted content</i>"]
    A --> B["find the span<br/>chars 12 → 38"]
    B --> C["split_at(p, 38)<br/>split_at(p, 12)<br/><i>force a run boundary at each end</i>"]
    C --> D["now every run is<br/>wholly in or wholly out"]
    D --> E["wrap them"]
```

`textmap.py` builds the map and does the splitting; `edits.py` does the wrapping.

---

## What gets written

```mermaid
flowchart TB
    START(["replace 'thirty (30) days'<br/>with 'forty-five (45) days'"])
    START --> DEL["<b>w:del</b><br/>wraps the old runs<br/>w:t → <b>w:delText</b>"]
    DEL --> INS["<b>w:ins</b><br/>new run, inserted after"]
    INS --> RESULT["~~thirty (30) days~~ forty-five (45) days"]

    style DEL fill:#fce8e6,stroke:#ea4335
    style INS fill:#e6f4ea,stroke:#34a853
```

`w:t` **must** become `w:delText` inside a `w:del`. Files that skip this still
open, but the text reappears in odd places on accept.

---

## Every kind of change

| Change | Markup |
|---|---|
| Insert text | `w:ins` around the new runs |
| Delete text | `w:del` + `w:t`→`w:delText` |
| Replace | `w:del` then `w:ins` |
| Insert a paragraph | `w:ins` + inserted ¶ mark (`w:pPr/w:rPr/w:ins`) |
| Delete a paragraph | `w:del` + deleted ¶ mark |
| Move | `w:moveFrom` / `w:moveTo` + range markers |
| Insert / delete a table row | `w:trPr/w:ins` / `w:trPr/w:del` |
| Character formatting | `w:rPrChange` carrying the *previous* `w:rPr` |
| Paragraph formatting | `w:pPrChange` carrying the *previous* `w:pPr` |

### The paragraph mark is the part people get wrong

Deleting a paragraph is not just striking its runs — the ¶ mark itself carries
`w:pPr/w:rPr/w:del`. Get it wrong and Word merges the wrong paragraphs on accept.

```mermaid
flowchart LR
    subgraph before ["before"]
        B1["¶ A"] --> B2["¶ B <i>(mark deleted)</i>"] --> B3["¶ C"]
    end
    subgraph after ["after accept"]
        A1["¶ A"] --> A2["¶ C"]
    end
    before ==> after
```

---

## Nesting rules that actually matter

```mermaid
flowchart TB
    OK1["✅ w:ins ▸ w:del<br/><i>'I inserted this, then deleted it'</i>"]
    NO1["❌ w:ins ▸ w:ins<br/><i>invalid — split the outer one instead</i>"]
    OK2["✅ w:del inside w:hyperlink"]
```

Editing text a previous pass inserted therefore **splits** the enclosing `w:ins`
rather than nesting inside it (`_escape_non_nestable`, `edits.py`).

---

## Moving a paragraph that was already edited

A `w:moveTo` copy cannot carry the source's own strikeouts — the deleted runs end
up *outside* the wrapper and reappear on reject.

```mermaid
flowchart TB
    Q{"does the paragraph<br/>already carry revisions?"}
    Q -->|no| MOVE["<b>move revision</b><br/>w:moveFrom / w:moveTo<br/><i>Word shows 'Moved from/to'</i>"]
    Q -->|yes| CUT["<b>cut &amp; paste</b><br/>delete at source +<br/>insert the accepted text<br/><i>warned in the report</i>"]

    style MOVE fill:#e6f4ea,stroke:#34a853
    style CUT fill:#fef7e0,stroke:#f9ab00
```

This is what Word's own Compare does for edited-and-moved blocks.

---

## Proving it, without Word

```mermaid
flowchart LR
    ORIG[["original"]] --> RL["redline"]
    RL -->|accept_all| ACC[["accepted"]]
    RL -->|reject_all| REJ[["rejected"]]
    REJ -.->|"must equal"| ORIG

    style REJ fill:#e6f4ea,stroke:#34a853
    style ORIG fill:#e8f0fe,stroke:#4285f4
```

`review.py` resolves the markup both ways: unwrap `w:ins` / drop `w:del` to
accept, the reverse to reject, merging paragraphs where a ¶ mark disappears.
`reject == original` is the single strongest check in the codebase.

---

## Where to look

| | |
|---|---|
| `textmap.py` | flat character map, run splitting |
| `edits.py` | `w:ins` / `w:del` / ¶-marks / rows / `*PrChange` |
| `redline.py` | `Redliner` — the public API |
| `review.py` | `accept_all` / `reject_all` / `summarize` |

**Next:** [Document structure →](02-document-structure.md)
