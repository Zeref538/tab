"""Watch a folder and read receipts as they land, without being asked.

    tab watch ./receipts

This is the part that makes TAB an agent rather than a tool you operate. Drop
twenty files in the folder, walk away, and the only thing that ever appears on
screen is the handful that need a person. Everything that added up is already
in the ledger.

Polling, not filesystem events. `os.scandir` on a folder of a few thousand files
costs about a millisecond, watching runs every few seconds, and the alternative
is a dependency plus three code paths for three operating systems. When the
folder holds a million files, revisit.

Three things that only matter because nobody is watching:

*Half-written files.* A file being copied in exists on disk before it is
finished. Reading it gives a truncated image and a hash that belongs to nothing.
So a file is only read once its size and timestamp have stopped changing.

*Two watchers.* Both would call the model on the same receipt and pay twice for
one answer. A lockfile beside the ledger prevents it, and is refreshed every
poll so that a watcher killed without warning does not lock the ledger forever.

*A stopped model.* Handled where it belongs, in tab.pipeline: a receipt the
model never saw is left on disk rather than recorded and skipped. Here it just
means waiting and saying so once.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from tab import pipeline, store
from tab.errors import ModelUnavailable

POLL_SECONDS = 5.0

# How long a file must sit untouched before it counts as finished being written.
SETTLE_SECONDS = 2.0

# A lock older than this belonged to a process that died. Generous on purpose:
# a slow vision extraction can hold a poll open for a minute or more, and
# stealing the lock from a watcher that is merely busy is worse than waiting.
STALE_AFTER = 300.0


class Lock:
    """One watcher per ledger, without a dependency.

    A plain "does the file exist" lock strands the ledger when the process is
    killed. This one carries a timestamp that the holder refreshes every poll,
    so a dead watcher's lock expires on its own.
    """

    def __init__(self, db_path: str | Path, stale_after: float = STALE_AFTER):
        self.path = Path(str(db_path) + ".watch.lock")
        self.stale_after = stale_after

    def held_by_someone_else(self) -> int | None:
        """The live holder's pid, or None if the lock is free or expired."""
        try:
            pid, stamp = self.path.read_text(encoding="utf-8").split()
        except (OSError, ValueError):
            return None
        if time.time() - float(stamp) > self.stale_after:
            return None
        return int(pid)

    def take(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Written whole to a neighbour then moved into place, so a reader never
        # sees half a line and decides the lock is corrupt.
        tmp = self.path.with_suffix(".lock.tmp")
        tmp.write_text(f"{os.getpid()} {time.time()}", encoding="utf-8")
        os.replace(tmp, self.path)

    def release(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass


class Watcher:
    """Holds what it has already looked at, so a poll costs a directory listing.

    Kept as an object with a `poll` you can call once, because a loop with a
    sleep in it cannot be tested without waiting.
    """

    def __init__(self, conn, folders: list[Path], use_model: bool = True,
                 report=print):
        self.conn = conn
        self.folders = [Path(f) for f in folders]
        self.use_model = use_model
        self.report = report
        self.done: set[tuple[str, int, float]] = set()   # path, size, mtime
        self.settling: dict[str, tuple[int, float]] = {}
        self.model_is_down = False
        self.totals = {"committed": 0, "needs_review": 0, "unreadable": 0,
                       "duplicate": 0}

    def _candidates(self) -> list[Path]:
        found = []
        for folder in self.folders:
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob("*")):
                if path.is_file() and path.suffix.lower() in pipeline.SUPPORTED:
                    found.append(path)
        return found

    def _ready(self, path: Path) -> bool:
        """True once the file has stopped changing.

        A file still being copied grows between polls. Reading it early gives a
        truncated image, and worse, records the hash of a file that will never
        exist again - so the finished copy looks like a different receipt and
        the broken one sits in quarantine forever.
        """
        try:
            stat = path.stat()
        except OSError:
            return False
        if stat.st_size == 0:
            return False
        # A file nobody has touched in a while is finished. Without this, the
        # twenty receipts already sitting in the folder when the watcher starts
        # would all wait a full poll for no reason.
        # ponytail: a copy that stalls mid-way for longer than this reads early;
        # the fix is a real file-lock probe, worth it only if it ever happens.
        if time.time() - stat.st_mtime > SETTLE_SECONDS:
            return True
        key = str(path)
        seen = self.settling.get(key)
        self.settling[key] = (stat.st_size, stat.st_mtime)
        return seen == (stat.st_size, stat.st_mtime)

    def poll(self) -> int:
        """One pass. Returns how many files were read this time."""
        read_this_pass = 0
        for path in self._candidates():
            try:
                stat = path.stat()
            except OSError:
                continue
            fingerprint = (str(path), stat.st_size, stat.st_mtime)
            if fingerprint in self.done or not self._ready(path):
                continue

            try:
                result = pipeline.ingest_one(self.conn, path,
                                             use_model=self.use_model)
            except ModelUnavailable as exc:
                # The file is untouched and unrecorded. Say it once, then wait.
                if not self.model_is_down:
                    self.report(f"waiting: {exc}")
                    self.report("  receipts are staying where they are until it answers.")
                    self.model_is_down = True
                return read_this_pass

            if self.model_is_down:
                self.report("the model is answering again.")
                self.model_is_down = False

            self.done.add(fingerprint)
            read_this_pass += 1
            outcome = "committed" if result["outcome"] == "commit" else result["outcome"]
            self.totals[outcome] = self.totals.get(outcome, 0) + 1

            # Only what needs a person gets said out loud. A receipt that added
            # up is in the ledger and there is nothing to decide about it.
            if outcome == "needs_review":
                self.report(f"  needs you  {path.name}: {result['why']}")
            elif outcome == "unreadable":
                self.report(f"  unreadable {path.name}: {result['why']}")
        return read_this_pass


def run(db_path: str | Path, folders: list[str], use_model: bool = True,
        interval: float = POLL_SECONDS, report=print) -> int:
    """Watch until interrupted."""
    lock = Lock(db_path)
    holder = lock.held_by_someone_else()
    if holder is not None:
        report(f"another watcher (pid {holder}) already has {Path(db_path).name}.")
        report(f"if that is wrong, delete {lock.path}")
        return 1

    conn = store.connect(db_path)
    watcher = Watcher(conn, [Path(f) for f in folders], use_model=use_model,
                      report=report)
    waiting = len(store.queue(conn))
    report(f"watching {', '.join(str(f) for f in folders)}")
    report(f"ledger: {db_path}" + (f" - {waiting} already waiting" if waiting else ""))
    report("only receipts that need you will appear here. Ctrl-C to stop.")

    lock.take()
    try:
        while True:
            lock.refresh()
            watcher.poll()
            time.sleep(interval)
    except KeyboardInterrupt:
        report("")
        t = watcher.totals
        report(f"stopped. {t['committed']} committed, {t['needs_review']} need review, "
               f"{t['unreadable']} unreadable, {t['duplicate']} already known.")
        return 0
    finally:
        lock.release()
        conn.close()
