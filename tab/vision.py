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
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import jsonschema

from tab.receipt import RECEIPT_SCHEMA, normalise

HOST = os.environ.get("TAB_OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = os.environ.get("TAB_VISION_MODEL", "qwen2.5vl:3b")

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
    b64 = base64.b64encode(Path(image).read_bytes()).decode()
    payload = {
        "model": model,
        "prompt": PROMPT,
        "images": [b64],
        "format": "json",
        "stream": False,
        # Temperature 0: the same receipt should read the same way twice.
        "options": {"temperature": 0},
    }

    started = time.time()
    last_error = None
    for attempt in range(1, tries + 1):
        try:
            response = _post(payload, host, timeout)
            raw = _parse(response.get("response", ""))
            receipt = normalise(raw)
            jsonschema.validate(receipt, RECEIPT_SCHEMA)
        except (json.JSONDecodeError, jsonschema.ValidationError,
                urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            continue
        return receipt, {
            "model": model,
            "attempts": attempt,
            "seconds": round(time.time() - started, 1),
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
