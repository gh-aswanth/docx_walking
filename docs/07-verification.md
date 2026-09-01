# 7 · Verification

*How the result is proven correct, without opening Word.*

---

## The central invariant

```mermaid
flowchart LR
    ORIG[["original.docx"]] --> RL["redline.docx"]
    RL -->|accept_all| ACC[["the intended<br/>new document"]]
    RL -->|reject_all| REJ[["the original,<br/>exactly"]]
    REJ -.->|"must be identical"| ORIG

    style ORIG fill:#e8f0fe,stroke:#4285f4
    style ACC fill:#e6f4ea,stroke:#34a853
    style REJ fill:#e6f4ea,stroke:#34a853
```

`accept_all` / `reject_all` are not conveniences — they are how the test suite
proves the markup is *semantically* right without a copy of Word. Verified to
survive nested `w:ins`/`w:del` and stacked moves.

---

## The seven checks

```mermaid
flowchart TB
    V1["1 · the redline reopens as a valid docx"]
    V2["2 · <b>reject restores the original document</b>"]
    V3["3 · accept changes it<br/><i>flips to 'leaves it unchanged'<br/>on an annotation-only run</i>"]
    V4["4 · no tracked changes survive accept"]
    V5["5 · reject restores the original numbering"]
    V6["6 · accepted numbering is contiguous<br/><i>every sibling group is 1..n</i>"]
    V7["7 · no cross-reference was broken"]

    V1 --> V2 --> V3 --> V4 --> V5 --> V6 --> V7

    style V2 fill:#e6f4ea,stroke:#34a853
    style V7 fill:#fef7e0,stroke:#f9ab00
```

Checks 6 and 7 only run when renumbering is on — with `--no-renumber`,
inconsistent numbering is the expected outcome, not a failure.

---

## Check 7 measures a delta, not an absolute

This is the one worth understanding. A real contract is full of references that
look dangling and that your redline had nothing to do with:

```mermaid
flowchart TB
    SCAN["scan for 'Section N', 'Clause N', 'Article N'…"] --> FOUND
    FOUND["found in a real contract"] --> F1["Section 5 of the <b>Master Services Agreement</b>"]
    FOUND --> F2["Section 12 of the <b>Uniform Commercial Code</b>"]
    FOUND --> F3["<b>Exhibit B</b>, Section 2 — exhibit-local numbering"]
    F1 & F2 & F3 --> BAD["an absolute check FAILS on run one<br/>for reasons that are not your redline"]
    BAD --> IGNORE["…and the team learns to ignore it"]

    style BAD fill:#fce8e6,stroke:#ea4335
    style IGNORE fill:#fce8e6,stroke:#ea4335
```

So the check baselines against the original and asserts only what changed:

```mermaid
flowchart LR
    B["broken references<br/>in the <b>original</b>"] --> D{"after − before"}
    A["broken references<br/>after <b>accept</b>"] --> D
    D --> R["only references<br/><b>this redline</b> broke"]

    style R fill:#e6f4ea,stroke:#34a853
```

---

## Where each failure is caught

Earlier is cheaper, and the message is more useful.

```mermaid
flowchart TB
    L1["<b>schema</b><br/>validate_actions"] --> L2["<b>merge pre-flight</b><br/>resolve against the untouched document"]
    L2 --> L3["<b>plan</b><br/>per-action failures, reported not raised"]
    L3 --> L4["<b>renumber</b><br/>clause-survival assertion"]
    L4 --> L5["<b>verify</b><br/>the seven checks"]

    L1 -.-> E1["unknown type · missing key ·<br/>duplicate id · bad severity"]
    L2 -.-> E2["clause 99.9 does not exist ·<br/>quote not found · ambiguous ·<br/>row out of range"]
    L3 -.-> E3["text moved since the model saw it"]
    L4 -.-> E4["a clause vanished that<br/>nothing asked to delete"]
    L5 -.-> E5["numbering broke · a reference broke ·<br/>reject did not restore"]

    style L1 fill:#e8f0fe
    style L2 fill:#e8f0fe
    style L5 fill:#fce8e6
```

---

## Independent confirmation

```mermaid
flowchart LR
    OURS[["our redline"]] --> LO["LibreOffice<br/><i>headless docx → docx</i>"]
    LO --> COUNT["count w:ins / w:del /<br/>moveFrom / moveTo / comments"]
    COUNT --> ASSERT{"survived?"}
    ASSERT -->|yes| PROOF["a real word processor<br/><b>understands</b> the markup —<br/>not merely well-formed XML"]

    style PROOF fill:#e6f4ea,stroke:#34a853
```

`scripts/demo_redline.py --libreoffice` runs this. LibreOffice drops
`w:rPrChange` on export — its own limitation, not ours — so character-formatting
revisions are excluded from that comparison. Word handles them.

---

## The test suite

**307 tests.** Almost all assert both directions of the round trip.

| File | Covers |
|---|---|
| `test_redline.py` | tracked-change primitives, run splitting, accept/reject |
| `test_addressing.py` | clause resolution, insert/delete/reorder correctness |
| `test_segments.py` | structure detection, whole-document rendering, ambiguity |
| `test_pipeline.py` | the renumbering cascade, action plans |
| `test_full_redline.py` | compare + actions + comments composed |
| `test_reviewers.py` | both providers via `httpx.MockTransport` |
| `test_chunked.py` | segmentation, triage floors, caching, concurrency |
| `test_merge.py` | every conflict and pre-flight rule |

Both providers are driven through their **real SDKs** with a mock transport — no
key, no network, but genuine request serialisation and response parsing.

```bash
uv run pytest -q                                    # 307 tests
uv run python scripts/demo_redline.py --libreoffice # self-check + LibreOffice
```

---

## What is still worth watching on a real 300-page run

```mermaid
flowchart TB
    W1["renumber blast radius<br/><i>one early insert can relabel thousands<br/>of clauses and every reference</i>"]
    W2["explain=True writing hundreds<br/>of Word comments<br/><i>the review pane gets heavy</i>"]
    W3["verify runs ~6-10 full-document passes<br/><i>correct, but slow at scale</i>"]

    style W1 fill:#fef7e0,stroke:#f9ab00
    style W2 fill:#fef7e0,stroke:#f9ab00
    style W3 fill:#fef7e0,stroke:#f9ab00
```

**Next:** [Document compare →](08-document-compare.md)
