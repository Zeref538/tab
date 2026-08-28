"""The ledger: one SQLite file the user owns.

No ORM. `sqlite3` is standard library, the schema fits on a page, and an ORM
would be a permanent dependency bought for a temporary convenience.
See docs/adr/0006-sqlite-as-the-ledger.md.

Constraints live in the database, not only in Python. A rule enforced in
application code is a rule a second entry point forgets — and this file will be
written by the CLI, the web app, and later an importer.

Every amount is an integer number of centavos. Floats cannot represent ₱0.10,
and the whole product is an equality test on money.
"""

from __future__ import annotations

import hashlib
import mimetypes
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from tab.receipt import AMOUNT_FIELDS

SCHEMA_VERSION = 1

DOCUMENT_STATUSES = ("pending", "committed", "needs_review", "quarantined", "discarded")
RECEIPT_STATUSES = ("committed", "needs_review", "discarded")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY,
    sha256      TEXT    NOT NULL UNIQUE,
    path        TEXT    NOT NULL,
    mime        TEXT    NOT NULL,
    pages       INTEGER NOT NULL DEFAULT 1,
    route       TEXT,
    status      TEXT    NOT NULL DEFAULT 'pending'
                CHECK (status IN {DOCUMENT_STATUSES!r}),
    ingested_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS extractions (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    method      TEXT    NOT NULL,
    model       TEXT,
    pass_no     INTEGER NOT NULL DEFAULT 1,
    raw_json    TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
    id               INTEGER PRIMARY KEY,
    document_id      INTEGER NOT NULL UNIQUE
                     REFERENCES documents(id) ON DELETE CASCADE,
    merchant         TEXT,
    tin              TEXT,
    or_number        TEXT,
    date             TEXT,
    currency         TEXT    NOT NULL DEFAULT 'PHP',
    subtotal         INTEGER,
    vatable_sales    INTEGER,
    vat_exempt_sales INTEGER,
    zero_rated_sales INTEGER,
    vat_amount       INTEGER,
    service_charge   INTEGER,
    discount_total   INTEGER,
    total            INTEGER,
    status           TEXT    NOT NULL CHECK (status IN {RECEIPT_STATUSES!r}),
    committed_at     TEXT,
    -- A committed row without a total would be a blank line in a tax filing.
    CHECK (status <> 'committed' OR total IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS line_items (
    id          INTEGER PRIMARY KEY,
    receipt_id  INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    line_no     INTEGER NOT NULL,
    description TEXT,
    qty         REAL,
    unit_price  INTEGER,
    amount      INTEGER,
    discount    INTEGER,
    -- A retry that re-inserts items must replace them, never double the
    -- subtotal. That bug would make item_sum fail on a correct receipt: the
    -- guard blaming good data, which is the worst kind of failure here.
    UNIQUE (receipt_id, line_no)
);

CREATE TABLE IF NOT EXISTS checks (
    id         INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    name       TEXT    NOT NULL,
    status     TEXT    NOT NULL CHECK (status IN ('pass', 'fail', 'skip')),
    detail     TEXT
);

CREATE TABLE IF NOT EXISTS corrections (
    id           INTEGER PRIMARY KEY,
    document_id  INTEGER NOT NULL,
    field        TEXT    NOT NULL,
    old_value    TEXT,
    new_value    TEXT,
    corrected_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL,
    step        TEXT    NOT NULL,
    action      TEXT    NOT NULL,
    why         TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);

-- Each index has a query behind it. An index with none is cargo cult, and on a
-- single-user file it costs write speed for nothing.
--   documents.sha256 is UNIQUE above: "have I already imported this exact file?"
CREATE INDEX IF NOT EXISTS ix_receipts_softdupe
    ON receipts (merchant, date, total);          -- same receipt, photographed twice
CREATE INDEX IF NOT EXISTS ix_receipts_status
    ON receipts (status);                          -- the review queue and the ledger
CREATE INDEX IF NOT EXISTS ix_line_items_receipt
    ON line_items (receipt_id);                    -- summing items for item_sum
CREATE INDEX IF NOT EXISTS ix_checks_receipt
    ON checks (receipt_id);                        -- which check failed, on screen
CREATE INDEX IF NOT EXISTS ix_decisions_document
    ON decisions (document_id);                    -- the reasoning trail
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_of(path: Path) -> str:
    """Hash the bytes in chunks — a scanned PDF can be large."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) and return a connection with sane pragmas."""
    path = Path(db_path)
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Off by default in SQLite, which surprises everyone once.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)

    found = conn.execute("PRAGMA user_version").fetchone()[0]
    if found == 0:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    elif found > SCHEMA_VERSION:
        raise SystemExit(
            f"{path} was written by a newer version of TAB (schema {found}, "
            f"this build understands {SCHEMA_VERSION}). Upgrade rather than "
            f"risk writing rows the newer schema cannot read.")
    # ponytail: forward migrations are one branch here when schema 2 exists.
    # Not written in advance — there is no shipped data to migrate yet, and a
    # migration path with nothing to migrate is untested code pretending to be
    # safety. When it lands it must back the file up first: the ledger is the
    # artefact and there is no re-running a stack of receipts.
    conn.commit()
    return conn


def register_document(conn: sqlite3.Connection, path: str | Path,
                      route: str | None = None) -> tuple[int, bool]:
    """Record a file. Returns (document_id, is_new).

    The hash lookup runs before any model does, so re-importing a folder costs
    a read of the bytes rather than a pass over every receipt in it.
    """
    p = Path(path)
    digest = sha256_of(p)
    row = conn.execute("SELECT id FROM documents WHERE sha256 = ?", (digest,)).fetchone()
    if row:
        return row["id"], False

    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    cur = conn.execute(
        "INSERT INTO documents (sha256, path, mime, pages, route, status, ingested_at)"
        " VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (digest, str(p.resolve()), mime, 1, route, now()))
    conn.commit()
    return cur.lastrowid, True


def log_decision(conn: sqlite3.Connection, document_id: int, step: str,
                 action: str, why: str) -> None:
    """Append-only. This is what the demo shows and what an audit reads."""
    conn.execute(
        "INSERT INTO decisions (document_id, step, action, why, created_at)"
        " VALUES (?, ?, ?, ?, ?)", (document_id, step, action, why, now()))
    conn.commit()


def find_soft_duplicate(conn: sqlite3.Connection, receipt: dict,
                        exclude_document_id: int | None = None) -> int | None:
    """The same receipt photographed twice: same shop, same day, same amount."""
    if not (receipt.get("merchant") and receipt.get("date")
            and receipt.get("total") is not None):
        return None
    row = conn.execute(
        "SELECT id FROM receipts WHERE merchant = ? AND date = ? AND total = ?"
        " AND status <> 'discarded' AND document_id IS NOT ? LIMIT 1",
        (receipt["merchant"], receipt["date"], receipt["total"],
         exclude_document_id)).fetchone()
    return row["id"] if row else None


def save(conn: sqlite3.Connection, document_id: int, receipt: dict, checks: list,
         status: str, method: str, raw_json: str, model: str | None = None,
         pass_no: int = 1) -> int:
    """Write one receipt, its items and its checks, in a single transaction.

    All of it or none of it. A crash mid-write must not leave a receipt with
    half its line items, because item_sum would then fail on good data forever.
    """
    if status not in RECEIPT_STATUSES:
        raise ValueError(f"unknown receipt status {status!r}")

    with conn:  # one transaction; rolls back on any exception
        conn.execute(
            "INSERT INTO extractions (document_id, method, model, pass_no,"
            " raw_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (document_id, method, model, pass_no, raw_json, now()))

        amounts = tuple(receipt.get(f) for f in AMOUNT_FIELDS)
        committed_at = now() if status == "committed" else None
        cur = conn.execute(
            "INSERT INTO receipts (document_id, merchant, tin, or_number, date,"
            " currency, subtotal, vatable_sales, vat_exempt_sales,"
            " zero_rated_sales, vat_amount, service_charge, discount_total,"
            " total, status, committed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (document_id) DO UPDATE SET"
            "   merchant=excluded.merchant, tin=excluded.tin,"
            "   or_number=excluded.or_number, date=excluded.date,"
            "   currency=excluded.currency, subtotal=excluded.subtotal,"
            "   vatable_sales=excluded.vatable_sales,"
            "   vat_exempt_sales=excluded.vat_exempt_sales,"
            "   zero_rated_sales=excluded.zero_rated_sales,"
            "   vat_amount=excluded.vat_amount,"
            "   service_charge=excluded.service_charge,"
            "   discount_total=excluded.discount_total, total=excluded.total,"
            "   status=excluded.status, committed_at=excluded.committed_at"
            " RETURNING id",
            (document_id, receipt.get("merchant"), receipt.get("tin"),
             receipt.get("or_number"), receipt.get("date"),
             receipt.get("currency") or "PHP", *amounts, status, committed_at))
        receipt_id = cur.fetchone()[0]

        # Replace, never append: a second pass must not double the subtotal.
        conn.execute("DELETE FROM line_items WHERE receipt_id = ?", (receipt_id,))
        conn.executemany(
            "INSERT INTO line_items (receipt_id, line_no, description, qty,"
            " unit_price, amount, discount) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(receipt_id, i["line_no"], i.get("description"), i.get("qty"),
              i.get("unit_price"), i.get("amount"), i.get("discount"))
             for i in receipt.get("line_items") or []])

        conn.execute("DELETE FROM checks WHERE receipt_id = ?", (receipt_id,))
        conn.executemany(
            "INSERT INTO checks (receipt_id, name, status, detail)"
            " VALUES (?, ?, ?, ?)",
            [(receipt_id, c.name, c.status, c.detail) for c in checks])

        conn.execute("UPDATE documents SET status = ?, route = COALESCE(route, ?)"
                     " WHERE id = ?", (status, method, document_id))
    return receipt_id


def ledger(conn: sqlite3.Connection, status: str = "committed") -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM receipts WHERE status = ? ORDER BY date, id", (status,)
    ).fetchall()


def queue(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """What needs a human, newest last so the oldest is dealt with first."""
    return conn.execute(
        "SELECT r.*, d.path FROM receipts r JOIN documents d ON d.id = r.document_id"
        " WHERE r.status = 'needs_review' ORDER BY r.id").fetchall()
