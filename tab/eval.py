"""Score a run against gold labels. Four numbers, always reported together.

  field accuracy        did it read this specific field right
  straight-through      share committed with no human at all       <- the headline
  escalation precision  when it asked for help, was it right to
  silent error rate     committed, unchecked, and WRONG            <- the one that hurts

Straight-through alone is a boast, not a result: a system that commits
everything scores 100% and is worthless. Only the pair says anything.

The run is resumable. Predictions are appended as they finish, and re-running
skips documents already scored — an 85-minute pass must never restart from zero
because something died at receipt 90.

    python -m tab.eval --corpus cord --split test
    python -m tab.eval --corpus cord --split test --limit 10
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tab.checks import ARITHMETIC_CHECKS, DEFAULT_TOLERANCE, run as run_checks, verdict
from tab.vision import assert_ready, extract

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
LF = chr(10)

# CORD labels these five money fields and nothing else useful. Merchant, date,
# TIN, OR number and the VAT split are simply absent from that corpus, so they
# are NOT scored here — reporting accuracy on a field the gold set does not
# contain would be inventing a number. See docs/adr/0005.
CORD_SCORED_FIELDS = ["subtotal", "vat_amount", "service_charge",
                      "discount_total", "total"]
CORD_UNSCOREABLE = ["merchant", "date", "tin", "or_number",
                    "vatable_sales", "vat_exempt_sales", "zero_rated_sales"]


def load_gold(corpus: str, split: str) -> dict[str, dict]:
    path = ROOT / "data" / corpus / f"labels-{split}.jsonl"
    if not path.exists():
        raise SystemExit(f"No labels at {path}. Run: python data/fetch_{corpus}.py")
    with path.open(encoding="utf-8") as fh:
        return {r["document"]: r for r in map(json.loads, fh)}


def compare(pred: dict, gold: dict, fields: list[str]) -> dict:
    """Field-by-field agreement. None is a real value here: a discount line that
    is not on the receipt must not be invented, so None vs a number is a miss."""
    return {f: pred.get(f) == gold.get(f) for f in fields}


def arithmetic_verdict(checks) -> str:
    """The verdict using ONLY the self-consistency checks.

    The product also requires a merchant name and a date before it will commit a
    row. CORD labels neither, so on that corpus those rules escalate almost
    everything and drown out what is actually being measured here: whether a
    receipt agrees with itself. Both numbers get reported, never just the
    flattering one.
    """
    if any(c.failed for c in checks if c.name in ARITHMETIC_CHECKS):
        return "needs_review"
    if not any(c.name in ARITHMETIC_CHECKS and c.status == "pass" for c in checks):
        return "needs_review"
    return "commit"


def score(rows: list[dict]) -> dict:
    """Turn per-receipt records into the four numbers."""
    n = len(rows)
    if not n:
        return {}

    per_field = {}
    for f in CORD_SCORED_FIELDS:
        hits = sum(1 for r in rows if r["fields"].get(f))
        per_field[f] = {"correct": hits, "n": n, "accuracy": round(hits / n, 4)}

    def block(verdict_key: str, wrong) -> dict:
        committed = [r for r in rows if r[verdict_key] == "commit"]
        escalated = [r for r in rows if r[verdict_key] != "commit"]
        silent = [r for r in committed if wrong(r)]
        caught = [r for r in escalated if wrong(r)]
        return {
            "straight_through_rate": round(len(committed) / n, 4),
            "silent_error_rate": round(len(silent) / n, 4),
            "escalation_precision": (round(len(caught) / len(escalated), 4)
                                     if escalated else None),
            "committed": len(committed),
            "escalated": len(escalated),
        }

    # Two definitions of "wrong", because they answer different questions and
    # quoting only one of them would flatter the result.
    #
    #   total    - the number that lands in the ledger. The strict yardstick.
    #   any      - any scored field. A receipt whose VAT line is invented is a
    #              wrong row even when its total happens to be right.
    #
    # Measured on CORD, precision is 14% by the first and 64% by the second, so
    # naming which one a figure uses is not a formality.
    def wrong_total(r):
        return not r["fields"].get("total")

    def wrong_any(r):
        return not all(r["fields"].values())

    by_total = block("verdict", wrong_total)
    a_by_total = block("arithmetic_verdict", wrong_total)
    a_by_any = block("arithmetic_verdict", wrong_any)

    committed = [r for r in rows if r["verdict"] == "commit"]
    escalated = [r for r in rows if r["verdict"] != "commit"]

    return {
        "n": n,
        "field_accuracy": per_field,
        "unscoreable_fields": CORD_UNSCOREABLE,
        "straight_through_rate": by_total["straight_through_rate"],
        "silent_error_rate": by_total["silent_error_rate"],
        "escalation_precision": by_total["escalation_precision"],
        "escalated": len(escalated),
        "committed": len(committed),
        "arithmetic_only": a_by_total,
        "arithmetic_only_any_field": a_by_any,
        "totals_correct": sum(1 for r in rows if r["fields"].get("total")),
        "extraction_failures": sum(1 for r in rows if r.get("failed")),
        "median_seconds": round(sorted(r["seconds"] for r in rows)[n // 2], 1),
    }


def report(s: dict, corpus: str, model: str, tolerance: int) -> str:
    if not s:
        return "nothing scored"
    n = s["n"]
    lines = [
        f"corpus={corpus}  model={model}  n={n}  tolerance={tolerance} centavos",
        "",
        "field accuracy",
    ]
    for f, v in s["field_accuracy"].items():
        lines.append(f"  {f:<16} {v['accuracy']:6.1%}   ({v['correct']}/{v['n']})")
    lines += [
        f"  not scored on this corpus: {', '.join(s['unscoreable_fields'])}",
        "",
        f"straight-through rate  {s['straight_through_rate']:6.1%}   "
        f"({s['committed']}/{n} needed no human)",
        f"silent error rate      {s['silent_error_rate']:6.1%}   "
        f"(committed with a wrong total)",
        "escalation precision   "
        + (f"{s['escalation_precision']:6.1%}   "
           f"(of {s['escalated']} escalated, that many really were wrong)"
           if s["escalation_precision"] is not None else "   n/a (nothing escalated)"),
        "",
        "",
        "ignoring the merchant/date rules, which CORD cannot score",
        f"  straight-through     {s['arithmetic_only']['straight_through_rate']:6.1%}   "
        f"({s['arithmetic_only']['committed']}/{n})",
        "",
        "  wrong = the total is wrong (strict: the number in the ledger)",
        f"    silent error rate    {s['arithmetic_only']['silent_error_rate']:6.1%}",
        "    escalation precision "
        + (f"{s['arithmetic_only']['escalation_precision']:6.1%}"
           if s["arithmetic_only"]["escalation_precision"] is not None else "n/a"),
        "",
        "  wrong = any scored field is wrong (an invented VAT line is a bad row too)",
        f"    silent error rate    {s['arithmetic_only_any_field']['silent_error_rate']:6.1%}",
        "    escalation precision "
        + (f"{s['arithmetic_only_any_field']['escalation_precision']:6.1%}"
           if s["arithmetic_only_any_field"]["escalation_precision"] is not None else "n/a"),
        "",
        f"totals read correctly  {s['totals_correct']}/{n}",
        f"extraction failures    {s['extraction_failures']}",
        f"median seconds/receipt {s['median_seconds']}",
    ]
    return "\n".join(lines)


def gold_ceiling(corpus: str, split: str, tolerances: list[int]) -> dict:
    """How often the GOLD labels pass their own arithmetic.

    This is the ceiling. A perfect extractor still gets escalated whenever the
    hand-labelled truth disagrees with itself, so no straight-through rate on
    this corpus can honestly exceed this number. Reported before any model
    result, because a headline quoted without its ceiling is half a fact.
    """
    gold = load_gold(corpus, split)
    out = {}
    for tol in tolerances:
        clean = 0
        for record in gold.values():
            checks = run_checks(record["labels"], tol)
            if not any(c.failed for c in checks if c.name in ARITHMETIC_CHECKS):
                clean += 1
        out[str(tol)] = {"self_consistent": clean, "n": len(gold),
                         "rate": round(clean / len(gold), 4)}
    return out


def markdown(s: dict, ceiling: dict | None = None) -> str:
    """The results as a Markdown table, so no figure is ever retyped by hand.

    Every number that appears in a document or on a page comes from here. A
    hand-copied figure is how a write-up ends up quietly disagreeing with the
    study it describes.
    """
    n = s["n"]
    a = s["arithmetic_only"]
    b = s["arithmetic_only_any_field"]
    rows = [
        f"Measured on **{s['corpus']}**, n={n}, model `{s['model']}`, "
        f"tolerance {s['tolerance']} centavos.",
        "",
        "Two columns because \"wrong\" has two honest meanings: the total alone is",
        "the number that lands in the ledger, but an invented VAT line is a bad row",
        "too. Naming which one a figure uses is not a formality.",
        "",
        "| metric | wrong = total | wrong = any scored field |",
        "|---|---|---|",
        f"| straight-through rate | {a['straight_through_rate']:.1%} | "
        f"{b['straight_through_rate']:.1%} |",
        f"| **silent error rate** | {a['silent_error_rate']:.1%} | "
        f"{b['silent_error_rate']:.1%} |",
        "| escalation precision | "
        + (f"{a['escalation_precision']:.1%}" if a["escalation_precision"] is not None else "n/a")
        + " | "
        + (f"{b['escalation_precision']:.1%}" if b["escalation_precision"] is not None else "n/a")
        + " |",
        "",
        f"Under the product rules, which also require a merchant name and a date, "
        f"straight-through is {s['straight_through_rate']:.1%} — CORD labels neither "
        f"field, so that column measures the corpus, not the system.",
        "",
        "| field | accuracy | correct |",
        "|---|---|---|",
    ]
    for f, v in s["field_accuracy"].items():
        rows.append(f"| `{f}` | {v['accuracy']:.1%} | {v['correct']}/{v['n']} |")
    rows += [
        "",
        f"Not scored on this corpus, because it does not label them: "
        f"{', '.join('`' + f + '`' for f in s['unscoreable_fields'])}.",
        "",
        f"Extraction failures: {s['extraction_failures']}. "
        f"Median {s['median_seconds']}s per receipt.",
    ]
    if ceiling:
        top = ceiling[str(s["tolerance"])]
        rows += [
            "",
            f"**Ceiling:** {top['self_consistent']}/{top['n']} "
            f"({top['rate']:.1%}) of the gold labels pass their own arithmetic at "
            f"this tolerance. A perfect extractor is still escalated on the rest, "
            f"so no straight-through rate here can honestly beat that.",
        ]
    return "\n".join(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", default="cord")
    p.add_argument("--split", default="test")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--tolerance", type=int, default=DEFAULT_TOLERANCE)
    p.add_argument("--model", default=None)
    p.add_argument("--gold-ceiling", action="store_true",
                   help="how often the gold labels pass their own arithmetic, "
                        "at several tolerances. No model is called.")
    p.add_argument("--markdown", action="store_true",
                   help="also write the results table as Markdown")
    p.add_argument("--retry-failed", action="store_true",
                   help="re-attempt documents previously recorded as failed")
    p.add_argument("--rescore", action="store_true",
                   help="re-score existing predictions without calling the model")
    args = p.parse_args()

    if args.gold_ceiling:
        ceiling = gold_ceiling(args.corpus, args.split, [5, 100, 200, 1000, 20000])
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / f"ceiling-{args.corpus}-{args.split}.json").write_text(
            json.dumps(ceiling, indent=2), encoding="utf-8", newline=LF)
        print(f"gold labels that pass their own arithmetic ({args.corpus}/{args.split})")
        for tol, v in ceiling.items():
            print(f"  tolerance {tol:>6} centavos   {v['self_consistent']}/{v['n']}"
                  f"   {v['rate']:.1%}")
        print()
        print("No straight-through rate on this corpus can honestly beat the top row.")
        return

    gold = load_gold(args.corpus, args.split)
    RESULTS.mkdir(exist_ok=True)
    pred_path = RESULTS / f"predictions-{args.corpus}-{args.split}.jsonl"

    from tab.vision import MODEL
    model = args.model or MODEL

    done: dict[str, dict] = {}
    if pred_path.exists():
        with pred_path.open(encoding="utf-8") as fh:
            done = {r["document"]: r for r in map(json.loads, fh)}
        print(f"resuming: {len(done)} already extracted")

    targets = list(gold)[:args.limit] if args.limit else list(gold)
    todo = [d for d in targets
            if d not in done or (args.retry_failed and done[d].get("failed"))]
    if args.retry_failed:
        # Rewrite the file without the failed rows, so a successful retry does
        # not leave the old failure sitting behind it in the same file.
        keep = [r for r in done.values() if not r.get("failed")]
        with pred_path.open("w", encoding="utf-8", newline=LF) as fh:
            for r in keep:
                fh.write(json.dumps(r, ensure_ascii=False) + LF)
        done = {r["document"]: r for r in keep}

    if todo and not args.rescore:
        assert_ready(model)  # cheap guard in front of the expensive loop
        images = ROOT / "data" / args.corpus / "images"
        started = time.time()
        with pred_path.open("a", encoding="utf-8", newline=LF) as fh:
            for i, doc in enumerate(todo, start=1):
                began = time.time()
                try:
                    receipt, meta = extract(images / doc, model=model)
                    row = {"document": doc, "receipt": receipt, "failed": False,
                           "seconds": meta["seconds"], "attempts": meta["attempts"]}
                except Exception as exc:  # noqa: BLE001
                    # Each receipt is independent, so a bad one is recorded and
                    # the batch carries on. Stopping would throw away every
                    # receipt still queued behind it for no gain.
                    row = {"document": doc, "receipt": {}, "failed": True,
                           "error": f"{type(exc).__name__}: {exc}",
                           "seconds": round(time.time() - began, 1), "attempts": 3}
                    print(f"    ! {doc}: {type(exc).__name__}: {exc}", flush=True)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()  # crash-safe: a killed run keeps everything up to here
                done[doc] = row
                rate = (time.time() - started) / i
                print(f"  {i}/{len(todo)} {doc}  {row['seconds']}s"
                      f"  eta {(len(todo) - i) * rate / 60:.0f}m", flush=True)

    rows = []
    for doc in targets:
        row = done.get(doc)
        if not row:
            continue
        checks = run_checks(row["receipt"], args.tolerance)
        action, why = verdict(checks)
        rows.append({
            "document": doc,
            "verdict": action,
            "arithmetic_verdict": arithmetic_verdict(checks),
            "why": why,
            "failed": row.get("failed", False),
            "seconds": row.get("seconds", 0),
            "fields": compare(row["receipt"], gold[doc]["labels"], CORD_SCORED_FIELDS),
            "checks": {c.name: c.status for c in checks},
            "arithmetic_ran": any(c.name in ARITHMETIC_CHECKS and c.status == "pass"
                                  for c in checks),
        })

    s = score(rows)
    s["corpus"], s["model"], s["tolerance"] = args.corpus, model, args.tolerance
    out = RESULTS / f"scoreboard-{args.corpus}-{args.split}.json"
    out.write_text(json.dumps({"scoreboard": s, "rows": rows}, indent=2),
                   encoding="utf-8", newline=LF)
    print()
    print(report(s, args.corpus, model, args.tolerance))
    print()
    print(f"written: {out.relative_to(ROOT)}")

    if args.markdown:
        ceiling_path = RESULTS / f"ceiling-{args.corpus}-{args.split}.json"
        ceiling = (json.loads(ceiling_path.read_text(encoding="utf-8"))
                   if ceiling_path.exists() else None)
        md = RESULTS / f"scoreboard-{args.corpus}-{args.split}.md"
        md.write_text(markdown(s, ceiling), encoding="utf-8", newline=LF)
        print(f"written: {md.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
