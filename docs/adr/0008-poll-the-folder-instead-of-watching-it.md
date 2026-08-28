# 0008 — The watcher polls the folder rather than subscribing to it

Date: 2026-08-28
Status: accepted

Refines the note in [the plan](../../docs/TDD.md) that said to copy YODA's
`watch.py`, which uses the same approach for the same reasons.

## Context

`tab watch ./receipts` is what turns TAB from a tool you run into a thing that
runs. Drop files in a folder, walk away, come back to a ledger and a short list
of the ones that need a person.

There are two ways to know a file arrived.

**Subscribe.** The operating system tells you. On Windows that is
`ReadDirectoryChangesW`, on Linux `inotify`, on macOS `FSEvents`. In Python that
means the `watchdog` package, which wraps all three.

**Ask.** List the folder every few seconds and look for names you have not seen.

## Decision

Ask. `Path.rglob` on a poll, default every five seconds.

## Why

**The cost is nothing at this size.** Listing a folder of a few thousand files
takes about a millisecond. A receipt folder holds hundreds, not millions. Five
seconds of latency on a receipt you photographed an hour ago is not latency
anybody experiences.

**Events do not remove the hard part.** The genuinely difficult thing about
watching a folder is not *finding out* a file appeared — it is knowing when it
has finished arriving. A file being copied in exists on disk, with a name and a
size, long before the last byte lands. `watchdog` will happily hand you a
`FileCreatedEvent` for a JPEG that is 3% written. Read it then and you record
the sha256 of a file that will never exist again, so the finished copy looks
like a brand new receipt and the truncated one sits in quarantine forever.

Every serious use of `watchdog` therefore ends up polling the file's size until
it stops changing — which is the thing we were trying to avoid. So events buy
latency we do not need and leave the actual problem untouched.

**One code path instead of three.** `watchdog` behaves differently per platform
in ways that only show up on someone else's machine: coalesced events on macOS,
missing events on network drives, a hard limit on inotify watches under Linux.
Polling behaves the same everywhere, including on the OneDrive folder this repo
lives in, where the file system is partly synthetic.

**It is one fewer dependency.** TAB has two. See [ADR 0007](0007-stdlib-http-server-for-the-review-page.md)
for the same argument made about a web framework.

## Consequences

Up to one poll interval of delay before a receipt is read. Nobody will notice.

A file that stalls mid-copy for longer than `SETTLE_SECONDS` reads early. Marked
in the code. The fix is a real file-lock probe, worth writing the day it happens
and not before.

If a folder ever holds enough files that a listing becomes slow, this decision
gets revisited with a measurement rather than a feeling.

## What was not decided here

Whether a stopped Ollama should quarantine a receipt. That is
[ADR 0009](0009-a-stopped-model-is-not-a-bad-receipt.md), and it matters far
more than this one.
