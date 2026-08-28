"""The folder watcher, driven a poll at a time.

`Watcher.poll()` is called directly rather than running `watch.run`, because a
loop with a sleep in it can only be tested by waiting, and a test that waits is
a test nobody runs.

Run: pytest tests/test_watch.py -q      (or: python tests/test_watch.py)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tab import pipeline, store, watch  # noqa: E402
from tab.errors import ModelUnavailable  # noqa: E402
from tests.fixtures import CLEAN, WRONG_TOTAL, write_receipt_pdf  # noqa: E402


def watcher(tmp_path, **kw):
    """A watcher over an empty folder, with somewhere to collect its output."""
    said: list[str] = []
    folder = tmp_path / "drop"
    folder.mkdir(exist_ok=True)
    conn = store.connect(tmp_path / "tab.db")
    w = watch.Watcher(conn, [folder], use_model=False, report=said.append, **kw)
    return w, folder, said


def test_a_settled_file_is_read(tmp_path):
    w, folder, said = watcher(tmp_path)
    try:
        write_receipt_pdf(folder / "clean.pdf", CLEAN)
        assert w.poll() == 0, "the first look only notes the file down"
        assert w.poll() == 1, "the second look sees it has stopped changing"
        assert len(store.ledger(w.conn)) == 1
    finally:
        w.conn.close()


def test_a_file_still_being_written_is_left_alone(tmp_path):
    """The bug this prevents: a half-copied file is read, its hash recorded, and
    the finished copy then looks like a different receipt while the broken one
    sits in quarantine. Nobody is watching, so nobody notices."""
    w, folder, said = watcher(tmp_path)
    try:
        target = folder / "arriving.pdf"
        write_receipt_pdf(target, CLEAN)
        w.poll()
        target.write_bytes(target.read_bytes() + b"%still copying")  # it grew
        assert w.poll() == 0, "it changed between looks, so it is not finished"
        assert len(store.ledger(w.conn)) == 0
    finally:
        w.conn.close()


def test_a_file_that_was_already_there_does_not_wait(tmp_path):
    """Twenty receipts sitting in the folder at startup are finished by
    definition. Making them wait a poll each would be pure ceremony."""
    w, folder, said = watcher(tmp_path)
    try:
        path = write_receipt_pdf(folder / "old.pdf", CLEAN)
        old = time.time() - (watch.SETTLE_SECONDS + 5)
        import os
        os.utime(path, (old, old))
        assert w.poll() == 1
    finally:
        w.conn.close()


def test_only_what_needs_a_person_is_said_out_loud(tmp_path):
    """The whole point of unattended mode. A receipt that adds up is in the
    ledger and there is nothing to decide about it, so it gets no line."""
    w, folder, said = watcher(tmp_path)
    try:
        write_receipt_pdf(folder / "clean.pdf", CLEAN)
        w.poll()          # first look notes it down
        w.poll()          # second look reads it
        assert said == [], f"a clean receipt should be silent, said: {said}"

        write_receipt_pdf(folder / "wrong.pdf", WRONG_TOTAL)
        w.poll()          # first look notes it down
        w.poll()          # second look reads it
        assert len(said) == 1
        assert "needs you" in said[0]
        assert "wrong.pdf" in said[0]
    finally:
        w.conn.close()


def test_a_file_is_not_read_twice(tmp_path):
    w, folder, said = watcher(tmp_path)
    try:
        write_receipt_pdf(folder / "clean.pdf", CLEAN)
        w.poll()          # first look notes it down
        w.poll()          # second look reads it
        assert w.poll() == 0
        assert w.poll() == 0
        assert len(store.ledger(w.conn)) == 1
    finally:
        w.conn.close()


def test_a_receipt_the_model_never_saw_is_left_to_try_again(tmp_path):
    """The expensive bug, and the reason ModelUnavailable exists.

    Quarantining a document records its hash, and a recorded hash is skipped
    for good. Treat a stopped Ollama like an unreadable receipt and restarting
    it silently loses every receipt that arrived while it was down - with no
    error, because from the ledger's point of view they were already imported.
    """
    w, folder, said = watcher(tmp_path)
    real_read = pipeline.read
    try:
        write_receipt_pdf(folder / "photo.pdf", CLEAN)
        pipeline.read = lambda *a, **k: (_ for _ in ()).throw(
            ModelUnavailable("Ollama never answered at http://127.0.0.1:11434"))

        w.poll()          # first look notes it down
        w.poll()          # second look reads it
        assert len(store.ledger(w.conn)) == 0
        left = w.conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
        assert left == 0, "nothing may be recorded about a receipt nobody read"
        assert any("waiting" in s for s in said)

        w.poll()
        assert sum("waiting" in s for s in said) == 1, "said once, not every poll"

        pipeline.read = real_read          # Ollama came back
        assert w.poll() == 1
        assert len(store.ledger(w.conn)) == 1
        assert any("answering again" in s for s in said)
    finally:
        pipeline.read = real_read
        w.conn.close()


def test_one_watcher_per_ledger(tmp_path):
    """Two watchers would both call the model on the same receipt and pay twice
    for one answer."""
    db = tmp_path / "tab.db"
    first = watch.Lock(db)
    first.take()
    try:
        assert watch.Lock(db).held_by_someone_else() is not None
    finally:
        first.release()
    assert watch.Lock(db).held_by_someone_else() is None, "released"


def test_a_lock_left_by_a_dead_watcher_expires(tmp_path):
    """The orchestrator dies without a traceback. It must not take the ledger
    with it - a lock nobody can clear is a tool nobody can restart."""
    db = tmp_path / "tab.db"
    stale = watch.Lock(db, stale_after=0.01)
    stale.take()
    time.sleep(0.05)
    assert watch.Lock(db, stale_after=0.01).held_by_someone_else() is None


def test_the_watcher_refuses_to_start_twice(tmp_path):
    db = tmp_path / "tab.db"
    held = watch.Lock(db)
    held.take()
    said = []
    try:
        code = watch.run(db, [str(tmp_path)], report=said.append)
        assert code == 1
        assert any("already has" in s for s in said)
        assert any("delete" in s for s in said), "it must say how to clear it"
    finally:
        held.release()


def test_stopping_gives_back_the_lock_and_says_what_happened(tmp_path):
    """Ctrl-C is how this is meant to end, so it is not an error path. If the
    lock outlived the process the ledger would be unwatchable until someone
    found the file and deleted it."""
    db = tmp_path / "tab.db"
    said = []

    def interrupt(self):
        self.totals["committed"] = 3
        raise KeyboardInterrupt

    original, watch.Watcher.poll = watch.Watcher.poll, interrupt
    try:
        assert watch.run(db, [str(tmp_path)], report=said.append) == 0
    finally:
        watch.Watcher.poll = original

    assert any("stopped." in s and "3 committed" in s for s in said)
    assert not watch.Lock(db).path.exists(), "the lock must not outlive the watcher"


if __name__ == "__main__":
    import tempfile

    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
                fn(Path(d))
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} checks passed")
