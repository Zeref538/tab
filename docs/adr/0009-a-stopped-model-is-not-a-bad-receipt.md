# 0009 — A stopped model is not a bad receipt

Date: 2026-08-28
Status: accepted

## Context

TAB records the sha256 of every file it reads, before it reads it. That is what
makes re-running safe: import the same folder twice and the second run costs a
hash per file instead of a model pass per file. See
[ADR 0006](0006-sqlite-as-the-ledger.md).

The same property is a trap. **A recorded hash is skipped for good.** So the
moment a document is written down, the decision about it is permanent.

Until now `pipeline.ingest_one` caught every exception the same way:

```python
except Exception as exc:
    ...  status = 'quarantined'
```

Which is right for a receipt the model read and could not make sense of. Reading
it again would fail identically, so recording it and moving on is correct.

It is badly wrong for the other case. Consider a watcher running overnight while
Ollama is restarted for five minutes:

1. Twenty photographs land in the folder.
2. Every one fails, because nothing is listening on port 11434.
3. Every one is quarantined, hash recorded.
4. Ollama comes back.
5. Nothing happens. Ever. From the ledger's point of view those twenty receipts
   were already imported.

No error, no warning, no queue entry. Twenty receipts gone, and the failure is
invisible precisely because the deduplication is working correctly. This is the
silent error the whole project is built to avoid, arriving through the back door.

## Decision

Two exception types, in `tab/errors.py`:

- `ExtractionFailed` — the model was reached and could not produce a usable
  receipt. **A fact about the document.** Quarantine it.
- `ModelUnavailable(ExtractionFailed)` — the model was never reached.
  **A fact about the machine.** Delete the document row that was just written,
  let the exception out, and leave the file exactly where it is.

`ModelUnavailable` is raised only when *every* attempt died before Ollama
answered. A single connection blip that succeeds on retry is not it.

They live in their own module rather than in `tab.vision` so that
`tab.pipeline` can catch them without importing the vision stack — which drags
in `jsonschema` and is skipped entirely for a PDF that carries its own text.

## Consequences

`tab watch` says the model is down, once, and keeps looking. The receipts stay
on disk. When Ollama answers again it says so and picks them up. Nothing is
lost, and nothing is retried in a hot loop.

`tab ingest` propagates the error and stops, which is the right behaviour for a
command someone is watching: doing the remaining nineteen files the same broken
way helps nobody.

The subclass relationship means existing `except ExtractionFailed` handlers keep
catching both. Anything that must tell them apart has to say so explicitly,
which is the safer default.

The test that guards this is
`test_a_receipt_the_model_never_saw_is_left_to_try_again`. It is the most
valuable test in `tests/test_watch.py`, because the bug it prevents produces no
output at all.
