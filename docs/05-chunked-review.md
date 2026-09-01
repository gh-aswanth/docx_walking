# 5 · Chunked review

*How a 300-page contract gets reviewed.*

---

## Why not just send the whole thing

Measured on a synthetic 300-page contract: **~280K tokens, 4,200 clauses**.

```mermaid
flowchart TB
    Q{"how do you feed<br/>300 pages to a model?"}
    Q --> P["<b>page by page</b>"]
    Q --> W["<b>whole document</b>"]
    Q --> S["<b>by structure</b>"]

    P --> PX["❌ a .docx has no pages<br/>Word computes pagination at render time —<br/>there is no marker to split on"]
    W --> WX["⚠️ it fits a 1M window, but one call must emit<br/>300-800 items in one output; recall collapses<br/>across 250K tokens and every retry re-spends it"]
    S --> SX["✅ segment boundaries are clause boundaries —<br/>quotes stay whole, clause numbers stay resolvable"]

    style PX fill:#fce8e6,stroke:#ea4335
    style WX fill:#fef7e0,stroke:#f9ab00
    style SX fill:#e6f4ea,stroke:#34a853
```

| | tokens |
|---|---|
| Full body | ~280,000 |
| Titles index, all 4,200 clauses | ~24,000 |
| Sections index, 300 sections | ~2,300 |
| `ClauseTree` parse of 4,200 clauses | **0.02 s** |

Local work is free. The model is the only cost centre.

---

## The shape

```mermaid
flowchart TB
    DOC[["contract.docx"]] --> SEG["<b>segment</b><br/><i>structural boundaries, token budget</i>"]
    SEG --> IDX["<b>index</b><br/><i>titles only + local risk flags</i>"]
    IDX --> TRI["<b>triage</b><br/><i>one cheap call</i>"]
    TRI --> SEL{"per segment"}
    SEL -->|deep| M1["full read"]
    SEL -->|scan| M2["low effort,<br/>critical + high only"]
    SEL -->|skip| M3["not called<br/><i>recorded with a reason</i>"]
    M1 & M2 --> POOL["<b>map</b><br/><i>1 primed call, then a thread pool</i>"]
    POOL --> RED["<b>merge</b><br/><i>see doc 6</i>"]
    M3 -.-> RED
    RED --> PLAN[/"one action-item plan"/]
    PLAN --> FR["full_redline(actions=…)"]

    style TRI fill:#fef7e0,stroke:#f9ab00
    style RED fill:#e8f0fe,stroke:#4285f4
    style PLAN fill:#e6f4ea,stroke:#34a853
```

`ChunkedReviewer` satisfies the plain `Reviewer` protocol, so the pipeline needed
no change to accept it.

---

## Triage cannot silently drop content

Skipping is the one decision here that loses information without trace, so the
model's answer is advice, not authority.

```mermaid
flowchart TB
    MODEL["model returns<br/>deep / scan / skip"] --> F1{"segment not<br/>mentioned at all?"}
    F1 -->|yes| SCAN1["→ <b>scan</b>, never skip"]
    F1 -->|no| F2{"≥2 risk keyword<br/>families present?"}
    F2 -->|yes, and it said skip| SCAN2["→ <b>scan</b>"]
    F2 -->|no| F3{"do the 'deep' segments cover<br/>≥ min-coverage of the document?"}
    SCAN1 --> F3
    SCAN2 --> F3
    F3 -->|no| PROMOTE["promote the highest-risk<br/>segments until they do"]
    F3 -->|yes| DONE["final selection"]
    PROMOTE --> DONE

    style SCAN1 fill:#fef7e0,stroke:#f9ab00
    style SCAN2 fill:#fef7e0,stroke:#f9ab00
    style PROMOTE fill:#fef7e0,stroke:#f9ab00
```

Risk families are a **local, free** keyword scan — 13 of them (liability,
indemnity, termination, renewal, warranty, confidentiality, data, governing-law,
assignment, audit, insurance, IP, payment). They are the recall floor: if triage
misjudges, the keywords still pull the segment back in.

If the triage call itself fails, every segment is reviewed. `--no-triage` does
the same deliberately.

---

## The prompt layout inverts

For a single-shot review the **contract** is constant and the brief varies. For a
chunked run the **brief** is constant and the segment varies — so the brief moves
into the cached prefix.

```mermaid
flowchart TB
    subgraph cached ["cached prefix — byte-identical across every segment call"]
        direction TB
        P1["system prompt"]
        P2["&lt;review_brief&gt;"]
        P3["&lt;document_index&gt;"]
    end
    subgraph varies ["varies"]
        V1["&lt;instruction&gt;"]
        V2["&lt;segment id='S07'&gt;…&lt;/segment&gt;"]
    end
    cached --> varies

    style cached fill:#e6f4ea,stroke:#34a853
    style varies fill:#e8f0fe,stroke:#4285f4
```

- **Anthropic** — `cache_control: ephemeral` on the last invariant block.
- **OpenAI** — `prompt_cache_key` derived from that prefix **alone**, so all
  segments share one cache partition. Keying it on the varying part would give
  every segment its own and defeat caching entirely.

---

## Priming, then fanning out

```mermaid
sequenceDiagram
    participant R as ChunkedReviewer
    participant API as provider

    R->>API: segment 1 (synchronous)
    Note over R,API: writes the shared cache prefix once,<br/>and builds the SDK client on this thread
    API-->>R: items
    par bounded thread pool
        R->>API: segment 2
    and
        R->>API: segment 3
    and
        R->>API: segment N
    end
    Note over R,API: N-1 concurrent cold writes to the same<br/>prefix would each pay 1.25× — priming pays once
```

The SDKs already retry 429/5xx with backoff, so the outer loop only handles
*semantic* failures.

---

## Why a run can look hung — and what stops it

A reasoning-heavy review of one segment legitimately runs for minutes. Three
things make that survivable rather than silent:

```mermaid
flowchart TB
    A["<b>announce before blocking</b><br/><i>[sending] S00  1137 tok, deep</i>"]
    B["<b>stream the response</b><br/><i>a non-streaming request that long risks<br/>an HTTP read timeout</i>"]
    C["<b>bounded timeout</b><br/><i>--timeout, default 900s —<br/>the SDK alone would wait 600s then retry</i>"]

    style A fill:#e6f4ea,stroke:#34a853
    style B fill:#e6f4ea,stroke:#34a853
    style C fill:#e6f4ea,stroke:#34a853
```

```text
  [segment] clauses strategy
  [triage ] deep:3, scan:0, skip:0
  [map    ]       0/3   3 segment(s) to review, 3 at a time
  [sending] S00         1137 tok, deep
  [ok     ] S00   1/3
  [sending] S01         1179 tok, deep
  [sending] S02          729 tok, deep
  [ok     ] S01   2/3
  [ok     ] S02   3/3
```

> **A small document is one segment.** With `--segment-tokens 25000`, a 12-page
> contract does not split at all — triage is skipped and it is a single call.
> `--effort high` on a reasoning model is the slow part; try `--effort medium`
> first, and `--segment-tokens 8000` if you want visible progress on a
> mid-sized file.

---

## When a call goes wrong

```mermaid
flowchart TB
    CALL["emit()"] --> R{"result"}
    R -->|ok| DONE["cache it, keep the items"]
    R -->|truncated| T1["retry once with<br/>double the ceiling"]
    T1 --> T2{"still truncated?"}
    T2 -->|yes| SPLIT["<b>split the segment</b><br/>at a heading, review both halves"]
    T2 -->|no| DONE
    R -->|transient error| RETRY["retry, up to max_attempts"]
    RETRY --> FAILED["recorded as failed<br/><i>the run continues</i>"]
    R -->|no credentials| RAISE["<b>raise</b><br/><i>never degrade to 'no findings'</i>"]

    style RAISE fill:#fce8e6,stroke:#ea4335
    style SPLIT fill:#fef7e0,stroke:#f9ab00
```

A run where **every** segment failed also raises — an empty result would read as
a clean bill of health.

---

## Resumability

```mermaid
flowchart LR
    K["cache key = sha256 of<br/>provider · model · effort ·<br/>prompt version · brief · segment text"] --> C[("~/.cache/docx-redline/")]
    C --> HIT{"hit?"}
    HIT -->|yes| FREE["reuse — no call"]
    HIT -->|no| CALL["call, then store"]

    style FREE fill:#e6f4ea,stroke:#34a853
```

A run that dies on segment 12 of 20 resumes at zero cost. Editing the brief or
bumping the prompt version invalidates by construction, not by hand.
`--cache-dir`, `--no-cache`, `--refresh`.

---

## Running it

```bash
python -m docx_redline full contract.docx -o out.docx \
    --reviewer chunked --provider openai \
    --segment-tokens 25000 --concurrency 6 \
    --min-coverage 0.35 \
    --cache-dir .cache/review \
    --merge-report merge.json
```

```python
from docx_redline import ChunkedReviewer, full_redline

full_redline(src, out, reviewer=ChunkedReviewer("claude", segment_tokens=25_000))
```

---

## Where to look

| | |
|---|---|
| `chunked.py` | `ChunkedReviewer`, `build_index`, `SegmentCache`, triage floors |
| `segments.py` | `segment_document`, `DocSegment.split` |
| `agent.py` | `emit()` — the shared transport both providers use |

**Next:** [Merge & reconciliation →](06-merge-reconciliation.md)
