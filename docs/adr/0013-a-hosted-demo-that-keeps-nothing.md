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
