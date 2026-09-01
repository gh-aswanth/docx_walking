# 8 · Document compare

*Diffing two `.docx` files into one redline — Word's Compare, in Python.*

---

## What it does

```mermaid
flowchart LR
    V1[["v1.docx<br/><i>original</i>"]] --> C{{"compare"}}
    V2[["v2.docx<br/><i>revised</i>"]] --> C
    C --> OUT[["redline.docx<br/><i>tracked changes</i>"]]
    OUT -->|accept| A[["= v2"]]
    OUT -->|reject| R[["= v1"]]

    style OUT fill:#e6f4ea,stroke:#34a853
```

The redline is built **on top of v1**, so its styles, numbering, headers and
section setup are preserved. Paragraphs that only exist in v2 are grafted in
with their own formatting.

---

## How the diff is taken

```mermaid
flowchart TB
    B1["blocks of v1<br/><i>paragraphs + tables</i>"] --> SM["SequenceMatcher<br/><i>on normalised text</i>"]
    B2["blocks of v2"] --> SM
    SM --> OPS{"opcode"}
    OPS -->|equal| EQ["nothing<br/><i>tables still compared row by row</i>"]
    OPS -->|delete| DEL["delete_paragraph<br/>or mark rows deleted"]
    OPS -->|insert| INS["graft the paragraph in,<br/>mark it inserted"]
    OPS -->|replace| REP{"how similar?"}
    REP -->|"≥ 0.45"| DIFF["<b>word-level diff</b><br/><i>mark only what changed</i>"]
    REP -->|"< 0.45"| SWAP["delete + insert<br/><i>unrelated paragraphs</i>"]

    style DIFF fill:#e6f4ea,stroke:#34a853
    style SWAP fill:#fef7e0,stroke:#f9ab00
```

The similarity floor is what stops two unrelated paragraphs being diffed
word-by-word into unreadable confetti. Tune it with `similarity_floor`.

---

## Word-level, not whole-paragraph

```mermaid
flowchart LR
    A["<b>v1</b><br/>Payment is due within<br/>thirty (30) days."] --> D
    B["<b>v2</b><br/>Payment is due within<br/>forty-five (45) days."] --> D
    D{"diff"} --> R["Payment is due within<br/>~~thirty (30)~~ forty-five (45) days."]

    style R fill:#e6f4ea,stroke:#34a853
```

Rewriting the whole paragraph as one delete + one insert is valid but
unreadable. `oxml/diffing.py` tokenises on word boundaries, and coalesces edits
separated by only a space or two so a single change reads as one revision.

---

## Composing with an action plan

A compare and a scripted plan can run on the same document. Order matters:

```mermaid
flowchart LR
    C["<b>compare</b><br/>runs first"] --> A["<b>actions</b><br/>address the document<br/>the diff produced"] --> M["<b>comments</b><br/>anchor to finished text"] --> R["<b>renumber</b><br/>once, over the combined result"]

    style R fill:#e8f0fe,stroke:#4285f4
```

The planner is constructed **before** the compare, so its baseline numbering is
the original — and `finalize()` is deferred to the very end.

---

## Running it

```bash
# compare alone
python -m docx_redline compare v1.docx v2.docx -o redline.docx --author "Compare Bot"

# compare plus a plan plus comments
python -m docx_redline full v1.docx -o out.docx \
    --revised v2.docx --actions plan.json \
    --comment "10.2=Confirm the cap with finance."
```

```python
from docx_redline import redline_files, full_redline

stats = redline_files("v1.docx", "v2.docx", "redline.docx")
print(stats.format())
# paragraphs: 3 changed, 1 inserted, 0 deleted; rows: 0 inserted, 0 deleted; cells: 0 changed

full_redline("v1.docx", "out.docx", revised="v2.docx", actions="plan.json")
```

---

## Known limits

```mermaid
flowchart TB
    L1["paragraphs matched by <b>normalised text</b><br/><i>content moved a long way shows as<br/>delete + insert, not a move revision —<br/>use move_clause when you know it moved</i>"]
    L2["grafted paragraphs carry their own <code>numId</code><br/><i>if the two files use different numbering<br/>definitions, list numbering may need fixing</i>"]

    style L1 fill:#fef7e0,stroke:#f9ab00
    style L2 fill:#fef7e0,stroke:#f9ab00
```

---

## Where to look

| | |
|---|---|
| `editing/compare.py` | `compare_documents`, `compare_into`, `redline_files` |
| `oxml/diffing.py` | `diff_ops` — the word-level diff |
| `planning/pipeline.py` | how a compare composes with an action plan |

**Next:** [Failure modes →](09-failure-modes.md)
