"""Read a receipt photograph with an OCR engine instead of a vision model.

A vision model is asked to do two jobs at once: recognise the characters, and
work out what they mean. It is very good at the second and expensively mediocre
at the first — 11 of 100 CORD totals came back wrong, and re-reading them with a
hint fixed almost none, which says the digits were never seen properly rather
than misinterpreted (docs/adr/0011).

An OCR engine does only the first job, and does it in under a second. The second
job is already solved here: `tab.pdftext.parse` turns the text of a receipt into
the TAB shape, and it does not care whether that text came out of a PDF or out of
a photograph. So this module is mostly the bit in between — putting recognised
boxes back into reading order.

    pip install "tab-agent[ocr]"
    python -m tab.ocr path/to/receipt.jpg

Optional on purpose. TAB ships with three dependencies and ADR 0007 argued that
fourteen was too many for a web framework; it would be a poor look to quietly
add nine for a route that has not yet earned its place.
"""

from __future__ import annotations

import gc
import logging
import time
from pathlib import Path

from tab import pdftext

# A box's vertical centre may drift by this share of the median line height and
# still count as the same printed line. Receipts are photographed at an angle,
# so a row of text is never perfectly level.
LINE_TOLERANCE = 0.6

_engine = None


def engine():
    """One engine, built once. Loading the models costs about half a second."""
    global _engine
    if _engine is None:
        # It announces every model file it opens, at INFO, on every construction.
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        try:
            from rapidocr import RapidOCR
        except ImportError:
            raise SystemExit(
                'The OCR route needs one extra package:\n'
                '  pip install "tab-agent[ocr]"') from None
        _engine = RapidOCR()
    return _engine


def to_lines(boxes, texts) -> list[str]:
    """Put recognised boxes back into the order a person would read them.

    An OCR engine returns boxes, not a page: "60.000" and the word "Subtotal"
    beside it arrive as two unrelated results. Grouping them back into printed
    lines is what makes `SUBTOTAL   60.000` exist as a string for the parser to
    find a label and an amount in.
    """
    if not texts:
        return []
    items = []
    for box, text in zip(boxes, texts):
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append({"y": sum(ys) / len(ys), "x": min(xs),
                      "h": max(ys) - min(ys), "text": str(text).strip()})

    heights = sorted(i["h"] for i in items)
    typical = heights[len(heights) // 2] or 1
    slack = typical * LINE_TOLERANCE

    lines: list[list[dict]] = []
    for item in sorted(items, key=lambda i: i["y"]):
        if lines and abs(item["y"] - lines[-1][0]["y"]) <= slack:
            lines[-1].append(item)
        else:
            lines.append([item])

    out = []
    for row in lines:
        row.sort(key=lambda i: i["x"])
        # Joined with a wide gap rather than one space: pdftext takes the LAST
        # number on a line as the amount, and a label like "VAT (12%)" must not
        # end up glued to its value.
        out.append("   ".join(i["text"] for i in row if i["text"]))
    return [line for line in out if line]


def read(image: str | Path, max_edge: int | None = None) -> tuple[dict, dict]:
    """One photograph to a receipt, via characters rather than a model.

    `max_edge` shrinks the longest side before reading. **It defaults to None,
    meaning no resizing at all**, and that default is load-bearing: every OCR
    accuracy figure published for this project was measured on the images as
    they are. 64 of the 100 CORD test receipts are longer than 1280px and 21 are
    longer than 1600 - the largest is 4096 - so quietly capping here would change
    what the scoreboard means without changing the number printed beside it.
    That is ADR 0012's whole point, undone by a default argument.

    The hosted demo passes a cap explicitly, because size is a hosting problem
    rather than a reading one: a 3024x4032 phone photo peaks at 606 MB against a
    512 MB instance, so one upload takes the box down. See tab/demo.py.
    """
    path = Path(image)
    started = time.time()
    if max_edge:
        # jsonschema and PIL are both core dependencies, so this costs the
        # OCR-only install nothing it did not already have. Same function and
        # same cap as the vision path, rather than a second one to tune.
        from tab.vision import prepare_image

        source, image_meta = prepare_image(path, max_edge)
    else:
        source, image_meta = str(path), {"resized": False}
    result = engine()(source)
    boxes = getattr(result, "boxes", None)
    texts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None) or []

    lines = to_lines(boxes if boxes is not None else [],
                     texts if texts is not None else [])
    text = "\n".join(lines)
    receipt = pdftext.parse(text)

    # The detection step parks about 90 MB of numpy arrays in reference cycles,
    # so plain reference counting never frees them. Python's cycle collector
    # decides when to run by counting OBJECTS waiting, not bytes - and 90 MB
    # here is only a couple of dozen arrays, far too few to trip it. Measured:
    # RSS climbed 24 MB per read, dead linear, 1.1 GB after 40 reads, which
    # kills a 512 MB host after about fourteen requests. One collect holds it
    # flat at 174 MB over 60 reads, for 47 ms on a 520 ms read.
    gc.collect()

    return receipt, {
        "method": "ocr",
        "seconds": round(time.time() - started, 2),
        "lines": len(lines),
        "image": image_meta,
        # The engine's own confidence. Recorded because it is interesting, and
        # never read by anything that decides: confidence comes from the
        # arithmetic. See docs/adr/0003.
        "mean_score": round(sum(scores) / len(scores), 3) if len(scores) else None,
        "raw": text,
    }


def demo() -> None:
    """Boxes in, printed lines out. Runs without the engine installed."""
    def box(x, y, w=40, h=10):
        return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

    boxes = [box(200, 100), box(20, 102), box(20, 140), box(200, 141)]
    texts = ["1,190.00", "SUBTOTAL", "TOTAL", "1,190.50"]
    lines = to_lines(boxes, texts)
    assert lines == ["SUBTOTAL   1,190.00", "TOTAL   1,190.50"], lines

    # A box that sits a long way down starts a new line even when it is narrow.
    lines = to_lines([box(20, 100), box(20, 400)], ["TOTAL", "CASH"])
    assert lines == ["TOTAL", "CASH"], lines

    # Nothing recognised is not an empty receipt, it is no lines at all.
    assert to_lines([], []) == []
    assert to_lines([], None) == []
    print("tab.ocr: all checks passed")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        receipt, meta = read(sys.argv[1])
        print(f"{meta['lines']} lines in {meta['seconds']}s "
              f"(mean confidence {meta['mean_score']})")
        print(meta["raw"])
        print()
        for field, value in receipt.items():
            if field != "line_items":
                print(f"  {field:18} {value}")
        print(f"  line_items         {len(receipt['line_items'])}")
    else:
        demo()
