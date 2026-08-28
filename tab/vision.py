"""Read a receipt image with a local vision model, through Ollama.

The single rule here: **the model transcribes, Python computes.** Every field is
asked for as the exact string printed on the paper. Nothing is ever asked to be
added up, converted, or inferred, because a model doing arithmetic is a model
producing a confident wrong number that the guard then has to catch.

Ollama is spoken to over plain HTTP with urllib — no SDK, no dependency. Same
pattern as YODA/yoda/planner.py, which has been running this way for months.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import jsonschema
from PIL import Image

from tab.receipt import RECEIPT_SCHEMA, normalise

HOST = os.environ.get("TAB_OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = os.environ.get("TAB_VISION_MODEL", "qwen2.5vl:3b")
CONTEXT_TOKENS = int(os.environ.get("TAB_NUM_CTX", "8192"))

# Longest edge, in pixels, that an image is allowed to reach before it is
# scaled down. A calibration knob, and it needed one: a vision model turns an
# image into tokens roughly in proportion to its AREA, so a 3024x4096 photo
# produces far more tokens than any context window, and Ollama does not refuse
# it politely - the model runner crashes with a dropped connection.
#
# Measured on CORD: median receipt is 864x1296 and is untouched by this cap.
# Only the handful of giant photos are resized, and 1600px down the long edge
# still leaves faded thermal print legible, which is the thing that must not be
# traded away.
MAX_IMAGE_EDGE = int(os.environ.get("TAB_MAX_IMAGE_EDGE", "1600"))
# The floor a shrink-and-retry will not go below. Past this, a receipt is
# too small to read and a confident answer from it would be worthless.
MIN_IMAGE_EDGE = int(os.environ.get("TAB_MIN_IMAGE_EDGE", "640"))

PROMPT = """You are reading a photograph of a shop or restaurant receipt.

Copy what is printed. Do not calculate anything, do not add numbers up, do not
convert currencies, and do not fill in a value that is not visible on the paper.
If a field is not printed on this receipt, use null. A guess is worse than null.

Return ONLY a JSON object with exactly these keys:

{
  "merchant": "shop name at the top, or null",
  "tin": "taxpayer identification number, or null",
  "or_number": "official receipt / invoice number, or null",
  "date": "the date in YYYY-MM-DD form, or null",
  "currency": "ISO code such as PHP or IDR",
  "subtotal": "the subtotal line exactly as printed, or null",
  "vatable_sales": "VATable sales line, or null",
  "vat_exempt_sales": "VAT-exempt sales line, or null",
  "zero_rated_sales": "zero-rated sales line, or null",
  "vat_amount": "the VAT or tax line, or null",
  "service_charge": "the service charge line, or null",
  "discount_total": "the discount line, or null",
  "total": "the final amount due, exactly as printed",
  "line_items": [
    {
      "line_no": 1,
      "description": "item name as printed",
      "qty": "quantity as printed, or null",
      "unit_price": "price per unit as printed, or null",
      "amount": "line total as printed, or null",
      "discount": "discount on this line, or null"
    }
  ]
}

Keep amounts as the exact strings on the receipt, including separators, for
example "1,190.00" or "60.000". Include every item line you can see."""

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class ExtractionFailed(RuntimeError):
    pass


def assert_ready(model: str = MODEL, host: str = HOST) -> None:
    """Fail before the batch, not on the fortieth document.

    A cheap check in front of expensive work always pays: this catches a
    stopped Ollama or a model that was never pulled in about a second, instead
    of after thirty images have already been rendered.
    """
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=10) as resp:
            tags = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(
            f"Ollama is not answering at {host} ({exc}).\n"
            f"Start it, then try again:  ollama serve") from None

    names = {m["name"] for m in tags.get("models", [])}
    if model not in names and f"{model}:latest" not in names:
        raise SystemExit(
            f"The model {model!r} is not pulled.\n"
            f"Get it with:  ollama pull {model}\n"
            f"Pulled right now: {', '.join(sorted(names)) or 'nothing'}")


def prepare_image(path: Path, max_edge: int = MAX_IMAGE_EDGE) -> tuple[bytes, dict]:
    """Return image bytes small enough to survive the model, plus what was done.

    A photo taken on a modern phone is far larger than any receipt needs to be
    read. Left alone it either blows the context window or kills the runner.
    """
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as img:
        width, height = img.size
        if max(width, height) <= max_edge:
            return raw, {"resized": False, "size": [width, height]}

        scale = max_edge / max(width, height)
        new = (max(1, round(width * scale)), max(1, round(height * scale)))
        shrunk = img.convert("RGB").resize(new, Image.LANCZOS)

    buffer = io.BytesIO()
    shrunk.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue(), {"resized": True, "size": list(new),
                               "was": [width, height]}


def _post(payload: dict, host: str, timeout: int) -> dict:
    req = urllib.request.Request(
        f"{host}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _parse(text: str) -> dict:
    """Pull a JSON object out of whatever the model said."""
    cleaned = _FENCE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Models sometimes wrap the object in a sentence. Take the outermost
        # braces and try once more before giving up.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(cleaned[start:end + 1])


def extract(image: str | Path, model: str = MODEL, host: str = HOST,
            tries: int = 3, timeout: int = 300) -> tuple[dict, dict]:
    """Read one receipt image. Returns (receipt in TAB shape, metadata).

    Retries only on unusable output — malformed JSON or a shape the schema
    rejects. A receipt that parses but disagrees with itself is NOT retried
    here; that is the arithmetic guard's job, and it decides afterwards.
    """
    payload = {
        "model": model,
        "prompt": PROMPT,
        "images": [],
        "format": "json",
        "stream": False,
        "options": {
            # Temperature 0: the same receipt should read the same way twice.
            "temperature": 0,
            # A tall receipt becomes more image tokens than the 4096-token
            # default window holds — measured, a receipt photo came to 4105 and
            # Ollama returned 400 exceed_context_size_error. Shrinking the image
            # would be the wrong fix: small thermal print is exactly what has to
            # stay readable. Give it room instead.
            "num_ctx": CONTEXT_TOKENS,
        },
    }

    started = time.time()
    last_error = None
    edge = MAX_IMAGE_EDGE
    image_meta: dict = {}
    for attempt in range(1, tries + 1):
        data, image_meta = prepare_image(Path(image), edge)
        payload["images"] = [base64.b64encode(data).decode()]
        try:
            response = _post(payload, host, timeout)
            raw = _parse(response.get("response", ""))
            receipt = normalise(raw)
            jsonschema.validate(receipt, RECEIPT_SCHEMA)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            if 400 <= exc.code < 500:
                raise ExtractionFailed(
                    f"{Path(image).name}: {exc.code} from Ollama, not retried "
                    f"because the request itself is what it rejected: {detail}") from None
            # A 5xx here is the model runner dying, and on this workload that
            # means the image was still too big to survive. Retrying the same
            # bytes would fail the same way, so the retry is DIFFERENT: half the
            # edge, a quarter of the pixels. Retrying identically is just
            # waiting longer for the same answer.
            last_error = f"{exc} {detail}"
            edge = max(MIN_IMAGE_EDGE, edge // 2)
            continue
        except (json.JSONDecodeError, jsonschema.ValidationError,
                urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            continue
        return receipt, {
            "model": model,
            "attempts": attempt,
            "seconds": round(time.time() - started, 1),
            "image": image_meta,
            "raw": raw,
        }

    raise ExtractionFailed(
        f"{Path(image).name}: {tries} attempts, last error: {last_error}")


if __name__ == "__main__":
    import sys

    assert_ready()
    path = sys.argv[1]
    receipt, meta = extract(path)
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    print(f"\n{meta['seconds']}s, {meta['attempts']} attempt(s), {meta['model']}")
