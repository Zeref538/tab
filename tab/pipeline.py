"""One receipt, end to end: hash it, decide how to read it, check it, store it.

The routing decision here is the part that makes TAB an agent rather than a
batch job. A PDF carrying real text is parsed directly and costs nothing; only a
photograph needs the model. Every decision is written to the `decisions` table in
plain words, so the reason a receipt was escalated can be shown later rather than
guessed at.
"""

from __future__ import annotations

import gc
import json
import os
import tempfile
from pathlib import Path

from tab import pdftext, store
from tab.errors import ModelUnavailable
from tab.checks import run as run_checks, verdict
from tab.receipt import normalise, pesos

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED = IMAGE_SUFFIXES | PDF_SUFFIXES

# Resolution to render a PDF page at when it has no text worth reading. 200 dpi
# keeps small print legible; tab.vision caps the pixels afterwards anyway.
RENDER_DPI = 200


class Result(dict):
    """A plain summary of what happened to one document."""

    def line(self) -> str:
        if self["outcome"] == "duplicate":
            return f"{self['name']}: already imported, skipped"
        if self["outcome"] == "unreadable":
            return f"{self['name']}: could not read — {self['why']}"
        money = pesos(self.get("total"))
        mark = "committed" if self["outcome"] == "commit" else "needs review"
        return f"{self['name']}: {money} via {self['route']} — {mark}: {self['why']}"


def _render_first_page(pdf: Path) -> Path:
    """A PDF with no text layer is a picture of a receipt. Make it one.

    The name is random rather than derived from the PDF's, for two reasons. Two
    receipts called scan.pdf in different folders used to render over each
    other's file. And the caller deletes this afterwards — see read() — which it
    can only do safely if the name belongs to this call and nothing else.
    """
    import pymupdf

    with pymupdf.open(pdf) as doc:
        pixmap = doc[0].get_pixmap(dpi=RENDER_DPI)
    handle, out = tempfile.mkstemp(suffix=".png", prefix="tab-render-")
    os.close(handle)
    pixmap.save(out)
    return Path(out)


def read(path: Path, use_model: bool = True, reader: str = "vision",
         max_edge: int | None = None) -> tuple[dict, dict]:
    """Route, then extract. Returns (receipt, metadata) or raises.

    The route is chosen per document and the reason travels back in the
    metadata, so it can be logged rather than inferred.

    `reader` picks what recognises the characters once a document turns out to
    need recognising at all: the vision model, or the OCR engine. It changes
    nothing about the text-layer route, which still wins whenever a PDF has real
    text in it — that decision is about the document, not about the reader.
    ADR 0012 has the measured difference between the two.
    """
    suffix = path.suffix.lower()
    needs = "an OCR engine" if reader == "ocr" else "the model"

    if suffix in PDF_SUFFIXES:
        found = pdftext.extract(path)
        if found is not None:
            receipt, meta = found
            meta["why"] = (f"PDF carries a real text layer "
                           f"({meta['characters']} characters), so no model was needed")
            return receipt, meta
        if not use_model:
            raise ValueError("PDF has no text layer and the model is switched off")
        image = _render_first_page(path)
        why = f"PDF has no usable text layer, so the page was rendered and read by {needs}"
    elif suffix in IMAGE_SUFFIXES:
        if not use_model:
            raise ValueError(f"an image needs {needs}, and it is switched off")
        image = path
        why = f"a photograph has no text to read, so {needs} was used"
    else:
        raise ValueError(f"{suffix or 'no extension'} is not a receipt file")

    # Anything rendered above is a picture of somebody's receipt sitting in the
    # temp folder. It used to stay there for good - every scanned PDF anyone
    # ingested left one behind, named predictably, forever. It is deleted now
    # whether the read works or not.
    rendered = image if image != path else None
    try:
        if reader == "ocr":
            from tab.ocr import read as ocr_read   # imported late: optional extra

            # max_edge stays None unless a caller asks for it. See tab.ocr.read:
            # capping by default would change every published accuracy figure.
            receipt, meta = ocr_read(image, max_edge=max_edge)
            meta["why"] = why
            return receipt, meta

        from tab.vision import extract as vision_extract  # late: slow, optional

        receipt, meta = vision_extract(image)
        meta["method"] = "vision"
        meta["why"] = why
        return receipt, meta
    finally:
        if rendered is not None:
            try:
                os.unlink(rendered)
            except OSError:
                gc.collect()          # Windows will not delete a file still open
                try:
                    os.unlink(rendered)
                except OSError:
                    print(f"WARNING: could not delete {rendered}")


def ingest_one(conn, path: str | Path, use_model: bool = True) -> Result:
    """Take one file all the way to a ledger row or a place in the queue."""
    path = Path(path)
    document_id, is_new = store.register_document(conn, path)
    if not is_new:
        store.log_decision(conn, document_id, "ingest", "skipped",
                           "these exact bytes have been imported before")
        return Result(name=path.name, outcome="duplicate", document_id=document_id)

    try:
        raw, meta = read(path, use_model=use_model)
    except ModelUnavailable:
        # The model was never reached, so nothing is known about this receipt.
        # Quarantining it would record its hash and skip it forever, which is
        # how a five-minute Ollama restart silently eats a folder of receipts.
        # Forget we ever saw it and let the caller stop.
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        conn.commit()
        raise
    except Exception as exc:  # noqa: BLE001 — one bad file must not end a batch
        store.log_decision(conn, document_id, "extract", "failed",
                           f"{type(exc).__name__}: {exc}")
        conn.execute("UPDATE documents SET status = 'quarantined' WHERE id = ?",
                     (document_id,))
        conn.commit()
        return Result(name=path.name, outcome="unreadable", document_id=document_id,
                      why=f"{type(exc).__name__}: {exc}")

    store.log_decision(conn, document_id, "route", meta["method"], meta["why"])

    receipt = normalise(raw)
    checks = run_checks(receipt)
    action, why = verdict(checks)

    twin = store.find_soft_duplicate(conn, receipt, exclude_document_id=document_id)
    if twin is not None and action == "commit":
        # Same shop, same day, same amount. Might be a genuine second purchase,
        # might be the same slip photographed twice — a human decides, because
        # a duplicated row in a tax filing is expensive and silent.
        action = "needs_review"
        why = f"looks like receipt #{twin}: same merchant, date and total"

    status = "committed" if action == "commit" else "needs_review"
    store.save(conn, document_id, receipt, checks, status,
               method=meta["method"], raw_json=json.dumps(raw, ensure_ascii=False),
               model=meta.get("model"))
    store.log_decision(conn, document_id, "check", status, why)

    return Result(name=path.name, outcome=action, document_id=document_id,
                  route=meta["method"], total=receipt.get("total"), why=why,
                  checks=checks)


def gather(paths: list[str]) -> list[Path]:
    """Files, in a stable order, from any mix of files and folders."""
    found: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found += [f for f in sorted(p.rglob("*"))
                      if f.is_file() and f.suffix.lower() in SUPPORTED]
        elif p.is_file():
            found.append(p)
        else:
            raise SystemExit(f"not found: {p}")
    return found
