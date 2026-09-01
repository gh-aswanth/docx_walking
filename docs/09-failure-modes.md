# 9 · Failure modes

*What goes wrong, and where it gets caught.*

Most of these were real bugs in this codebase. Every one of them reported
`applied` while doing the wrong thing — which is why they are worth writing down.

---

## The shape of the danger

```mermaid
flowchart LR
    LOUD["<b>loud failures</b><br/>an exception, a failed check"] --> FINE["annoying, but fine —<br/>you know immediately"]
    QUIET["<b>quiet failures</b><br/>status: applied · result.ok: true"] --> BAD["a contract that is<br/>subtly wrong"]

    style FINE fill:#e6f4ea,stroke:#34a853
    style BAD fill:#fce8e6,stroke:#ea4335
```

Nearly all the work in `merge.py` and the guards in `actions.py` exist to move
things from the bottom row to the top.

---

## Where each class is caught

```mermaid
flowchart TB
    subgraph early ["caught before the document is opened"]
        E1["unknown action type · missing key"]
        E2["duplicate id across segments"]
        E3["clause 99.9 does not exist"]
        E4["quoted text not found, or ambiguous"]
        E5["reorder lists a foreign clause"]
        E6["table / row / col out of range"]
    end
    subgraph during ["caught while applying"]
        D1["a delete would swallow a clause<br/>something else moved in"]
        D2["a move relative to itself"]
        D3["text moved since the model saw it"]
    end
    subgraph after ["caught by verification"]
        A1["reject did not restore the original"]
        A2["numbering is not contiguous"]
        A3["a cross-reference broke"]
        A4["a clause vanished unbidden"]
    end
    early --> during --> after

    style early fill:#e8f0fe
    style after fill:#fce8e6
```

---

## The ones that used to be silent

### Ambiguous quotes edited the wrong paragraph

```mermaid
flowchart LR
    Q["a segment reviewing clause 40.2 emits<br/><code>find: 'thirty (30) days'</code><br/>with no <code>clause</code>"] --> S["scope widens to the whole body,<br/>first match wins"]
    S --> W["<b>clause 3.2 on page 1 is edited</b><br/>status: applied · no record of where"]

    style W fill:#fce8e6,stroke:#ea4335
```

**Now:** an unscoped quote matching more than one paragraph is refused, naming
the matches. `all: true` opts back in deliberately.

### A new clause stole its neighbour's number

`insert_clause before_clause="3.3"` mints a *second* clause labelled `3.3`, and
lookup was first-match-wins:

```mermaid
flowchart LR
    I["insert before 3.3"] --> DUP["two clauses now labelled 3.3"]
    DUP --> LATER["a later action targeting 3.3<br/>resolves to the <b>new</b> one"]
    LATER --> W["the comment lands on the insertion,<br/>not on the real Late Payment clause"]

    style W fill:#fce8e6,stroke:#ea4335
```

**Now:** lookup prefers the clause that was already there, duplicates are
reported, and inserts are ordered **last** so nothing resolves while one exists.

### A delete swallowed a clause that was moved into it

```mermaid
flowchart LR
    M["move 12.1 into §5"] --> D["delete §5"]
    D --> W["12.1 is gone —<br/>both actions reported <b>applied</b>"]

    style W fill:#fce8e6,stroke:#ea4335
```

**Now:** a delete refuses when its subtree contains anything moved or inserted
earlier in the run, and says which clauses. The merge stage also drops any
action targeting a delete closure.

### A credentials failure looked like a clean review

```mermaid
flowchart LR
    NOKEY["no API key"] --> CATCH["broad <code>except RuntimeError</code><br/>in the retry loop"]
    CATCH --> ALLFAIL["every segment 'failed'"]
    ALLFAIL --> W["<b>0 findings · result.ok: true</b>"]

    style W fill:#fce8e6,stroke:#ea4335
```

**Now:** `RedlineCredentialsError` propagates, and a run where every segment
failed raises rather than returning an empty plan.

### An `id()`-keyed map lost entries

Twice. lxml hands out element proxies on demand and frees them when the last
reference goes — so a `dict` keyed on `id(element)` silently loses entries, and
can start matching an unrelated element once CPython recycles the address.

```mermaid
flowchart LR
    MAP["dict[id(w:p)] = level"] --> GC["proxies freed<br/>after a tree reload"]
    GC --> W["4 headings found<br/>where 20 exist"]

    style W fill:#fce8e6,stroke:#ea4335
```

**Now:** either hold the elements alive in the map (`LabelSnapshot`) or use a
resolver function instead of a map (`level_resolver`).

---

## Failures that are *meant* to be loud

```mermaid
flowchart TB
    F1["schema-invalid action items<br/>→ nothing runs at all"]
    F2["a clause disappeared that no action deleted<br/>→ raise"]
    F3["every reviewed segment failed<br/>→ raise"]
    F4["missing credentials<br/>→ raise, naming the variable to set"]
    F5["reject did not restore the original<br/>→ result.ok is false, exit code 1"]

    style F1 fill:#fef7e0,stroke:#f9ab00
    style F2 fill:#fef7e0,stroke:#f9ab00
    style F3 fill:#fef7e0,stroke:#f9ab00
    style F4 fill:#fef7e0,stroke:#f9ab00
    style F5 fill:#fef7e0,stroke:#f9ab00
```

---

## Two gotchas that are not bugs

**`Paragraph.text` misses tracked insertions.** python-docx reads only `w:r`
children, so it cannot see anything inside a `w:ins` — every insertion this
library makes — while still returning text that has been struck out. Use
`rl.text_of(paragraph)`.

**LibreOffice drops `w:rPrChange` on export.** Its own limitation. Insert,
delete and move revisions survive it fine; Word handles formatting revisions
correctly.

---

## Reading a run that went wrong

```mermaid
flowchart TB
    START["result.ok is false"] --> Q1{"which stage?"}
    Q1 -->|validate| A1["the action items are malformed —<br/>see the problem list"]
    Q1 -->|plan| A2["some actions could not be applied —<br/>each result has a detail"]
    Q1 -->|verify| A3["the markup resolved wrongly —<br/>see which of the seven checks failed"]
    START --> Q2{"chunked run?"}
    Q2 -->|yes| A4["--merge-report accounts for every<br/>proposal: kept, dropped, conflicting,<br/>unresolvable — each with a reason"]
```

---

## Where to look

| | |
|---|---|
| `merge.py` | pre-flight, conflict rules, the report |
| `actions.py` | `_require_unique`, the delete guard, `_assert_no_clause_vanished` |
| `pipeline.py` | `verify` and the seven checks |
| `tests/test_merge.py` | one test per failure above |

**Back to:** [index](README.md)
