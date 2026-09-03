# 0013 — A hosted demo that keeps nothing

Date: 2026-09-03
Status: accepted — narrows [0004](0004-local-only-public-page-is-a-replay.md)

## The tension

ADR 0004 said receipts never leave the machine, and that the public page would
therefore be a *recording* of a real run rather than something you can use. That
was the right call for the product and it made the public page honest.

It also made TAB the only project here that a reader cannot try. The two that
land best — `callback-ai` and `aegix-ai` — are live things you click. `yoda` is
a replay on GitHub Pages, and TAB was built in the same shape. A tool nobody can
run is a tool nobody believes.

## The decision

There is a hosted demo at `/api/check` plus a page in front of it. It accepts a
receipt, reads it, checks the arithmetic, and answers. **It writes nothing
down.**

- No ledger, no database, not even a log line naming the file.
- The bytes exist as a temp file for the length of one request, because the
  readers open paths rather than buffers, and it is deleted in a `finally`.
- Every response carries `"stored": false`, so the API repeats the claim rather
  than leaving it on a marketing page.
- The reader is OCR, not the vision model, so no receipt is ever sent to any
  model — local or otherwise.

The product is unchanged: you run TAB on your own machine and nothing leaves it.
The demo exists so a stranger can see what it does before installing it.

## What this actually costs

Honestly: someone who uploads their own receipt has sent it to a server. That is
a real narrowing of 0004 and calling it anything else would be dishonest. Three
things make it defensible rather than a hole:

1. The page says so plainly, next to the upload box, before you use it.
2. Three sample receipts are one click away, so nobody has to upload anything to
   see the thing work.
3. Nothing is retained, and that is enforced by a test rather than by a promise
   (`tests/test_demo.py`).

## Two bugs this turned up, both about files on disk

Neither was in new code. Both were found by writing the test that says nothing
is left behind, which is the argument for writing it.

**A rendered receipt stayed in the temp folder forever.** A PDF with no text
layer gets rendered to an image so it can be read. `pipeline._render_first_page`
wrote that image to `tab-render-<name>.png` and nothing ever deleted it. Every
scanned receipt anyone ingested — through the CLI, not just the demo — left a
picture of itself on disk under a predictable name. Now it is a random name and
it is deleted whether the read succeeds or not.

**The failed-read path left the upload behind on Windows.** The delete was in a
`finally` with `except OSError: pass`, and Windows will not unlink a file while
anything still has it open — the live traceback held frames referencing the
reader. So the delete threw, the error was swallowed, and the docstring above it
claimed the opposite. The traceback is now dropped before the cleanup runs.

## And a third, found only by installing it properly

The OCR extra installed cleanly and then died on boot with
`ImportError: onnxruntime is not installed`.

rapidocr 3.x supports four inference engines — onnxruntime, paddle, torch,
openvino — and therefore declares **none** of them, leaving the choice to you.
TAB never made the choice. It ran here because onnxruntime happened to be on
this machine already, which is the same reason `pymupdf` went undeclared for a
week while three modules imported it.

No test could have found this one. `tests/test_packaging.py` reads the imports in
`tab/` and checks each against `pyproject.toml`, which catches the pymupdf shape
— but nothing here imports onnxruntime by name; rapidocr does, internally. The
only thing that finds it is an empty virtualenv, so that is now a script:
`python tools/check_install.py`. It installs into a fresh venv exactly as
`render.yaml` does, starts the demo **from a different directory**, and calls it
over HTTP. It is what turned this up.

Worth stating plainly: had this not been run, the Render deploy would have built
successfully and then crash-looped, and the page would have been a dead link.

## Two visitors at once used to kill it

Peak resident memory by number of simultaneous requests, measured against the
running server, against the 512 MB a free instance has:

| at once | 1 | 2 | 4 | 8 |
|---|---:|---:|---:|---:|
| before | 387 MB | 675 MB | 1113 MB | 1894 MB |
| after | 307 MB | 339 MB | 361 MB | 361 MB |

Wall clock for those same runs, before the fix: 1.0, 1.7, 3.4, 6.5 seconds.
Dead linear — the reads were already serialised by the interpreter lock, so
running them in parallel never made anything faster. It only spent memory. So
the fix costs nothing: one semaphore, one read at a time, a `503` with a
`Retry-After` when the queue is full rather than a hung connection.

A single **uncapped phone photo** was its own problem: 3024x4032 peaks at 606 MB,
over the ceiling by itself. Uploads are now shrunk to 1280px on the long edge
first.

That cap lives in `tab/demo.py`, **not** in `tab/ocr.py`, and the difference
matters. 64 of the 100 CORD test receipts are longer than 1280px and 21 are
longer than 1600 — the largest is 4096. Capping inside the reader would have
changed what every published OCR figure means while leaving the number beside it
untouched. Size is a hosting problem; the library keeps reading what it is given.

Re-scored on the same 100 receipts so the demo's own accuracy is known rather
than assumed:

| | uncapped | at 1280px |
|---|---:|---:|
| totals read | 73/100 | 72/100 |
| subtotal | 77/100 | 76/100 |
| VAT, service charge, discount | 71 / 94 / 94 | 71 / 94 / 94 |
| straight-through | 15% | 15% |
| silent error, any field | 2% | 2% |
| median seconds | 0.9 | 0.7 |

One total and one subtotal out of a hundred, for half the memory and a faster
read. Reproduce with:

    python -m tab.eval --corpus cord --split test --reader ocr --max-edge 1280

## Why Render, not Vercel or Pages

GitHub Pages serves files and cannot run a process, which is exactly why YODA's
demo had to be a recording. Vercel's functions are shaped for short bursts and
this holds ~175 MB of OCR models resident and wants them warm. Render runs an
ordinary long-lived Python process on a free instance, `render.yaml` describes it
in one file, and both `callback-ai` and `aegix-ai` already deploy this way — one
fewer thing to learn and one fewer thing to get wrong.

Measured before committing to it: the OCR route peaks at ~175 MB against the
free tier's 512 MB. It did **not** fit at first — see the note in `tab/ocr.py`
about the cycle collector, which is a better story than the number.

## What would change this

- A Philippine corpus (Gate D, ADR 0005) does not change any of the above, but
  it changes what the demo is allowed to claim while you use it.
- If the demo is ever asked to remember anything at all — a queue, a history, an
  account — this ADR stops applying and needs replacing, not amending.
