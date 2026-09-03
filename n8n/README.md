# TAB in an n8n flow

n8n is a tool where you wire boxes together instead of writing glue code:
*when an email arrives, do this, then that.* TAB is one box in the middle — the
one that decides whether a receipt can be filed without a person looking at it.

```
Gmail ──► TAB /api/check ──► Switch ──┬── verdict = commit ──────► Google Sheets
                                      └── verdict = needs_review ► Slack
```

Import `tab-receipt-check.json`: **Workflows → Import from File**.

## Prove it works before wiring anything up

`tab-smoke-test.json` is the same middle three boxes with no credentials at all
— a manual trigger, a file off disk, TAB, and a Switch that labels the result.
Import it, put a receipt path in the first node, press Test. If you see
`FILED` or `HELD`, your TAB is reachable and the rest is just plumbing.

Two n8n settings will stop it, and both fail in ways that do not mention n8n:

- **Reading a file off disk** is refused unless the folder is allowlisted:
  `N8N_RESTRICT_FILE_ACCESS_TO=/some/folder`. Otherwise: *"Access to the file is
  not allowed."*
- **`{{ $env.X }}` inside a node** is blocked unless
  `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`. Otherwise: *"access to env vars
  denied."* Both workflows here use a plain URL instead, so neither needs it.

## The one thing to set

The HTTP node calls `http://localhost:8000/api/check`. Open it and change that
to wherever your TAB is. Everything else works as imported, except the Sheets
node, which needs your own sheet id, and Slack, which needs your own channel.

## What each box does

**Receipt arrives by email** — a Gmail trigger filtered to messages with
attachments. Any trigger works instead: Drive, Dropbox, a webhook, or a schedule
that walks a folder. TAB does not care where the bytes came from.

**TAB checks the arithmetic** — one HTTP POST. The file goes as raw bytes with
its name in an `X-Filename` header. About a second per receipt. What comes back:

```json
{
  "verdict": "needs_review",
  "why": "line 3: 3.0 × ₱30.00 is ₱90.00, but the line reads ₱80.00",
  "route": "ocr",
  "seconds": 0.9,
  "flagged": ["subtotal", "item.3.amount"],
  "receipt": { "merchant": "...", "total": 31400, "line_items": [] },
  "checks": [{ "name": "line_math", "status": "fail", "detail": "..." }],
  "stored": false
}
```

`neverError` is switched on in that node deliberately. A receipt TAB cannot read
comes back as a normal item carrying an `error` field, so one unreadable
attachment does not kill the run and strand every receipt behind it.

**Does it add up?** — a Switch on `verdict`. Two ways out: `adds up` and
`needs a person`.

Branch on `verdict`, **never on a confidence score.** There isn't one, and that
is the whole design. A model that reports 95% certainty will state a wrong total
with exactly that much certainty. `verdict` is the output of arithmetic that
either reconciles or doesn't, so it is worth routing on.

**File it** — appends a row. Amounts arrive as whole centavos, as integers,
because `0.1 + 0.2` is not `0.3` in any language with floats and a peso is not
allowed to drift. The workflow divides by 100 exactly once, here, at the edge
where a person reads it.

**Ask a person** — posts `why` and `flagged` to Slack, so the message says
*which* line disagrees rather than "check this one".

## Why this is worth wiring up

Without TAB the Switch has nothing to switch on. You either file every receipt
unread — and a wrong total in a tax return is expensive and silent — or you read
all of them yourself, which is the job you were automating.

The measured split on 100 receipts: about 3 in 10 file themselves, and of the 11
whose total was misread, 10 were held back for a person. Numbers and method:
<https://zeref538.github.io/tab/>.

## What was actually verified

Both files were imported into a real n8n (`n8n import:workflow`) and exported
back out, and all five nodes survived with their types and versions intact.

`tab-smoke-test.json` was then **executed** against a running TAB, twice:

| receipt | route | seconds | verdict | branch taken |
|---|---|---:|---|---|
| `bad-line-math.png` | ocr | 1.13 | `needs_review` | Would go to a person |
| `clean.pdf` | text_layer | 0.01 | `commit` | Would be filed |

Each time the other branch did not run, which is the bit worth checking — a
Switch that fires both ways files receipts it should have held.

Two things that only showed up by running it, both now fixed here: a
hand-written workflow with no top-level `id` dies on import with
`NOT NULL constraint failed: workflow_entity.id`, and `{{ $env.* }}` inside a
node is blocked on a default install.

**Not verified:** the Gmail, Sheets and Slack nodes. They need credentials that
have no business in a repo. Their shape is checked by `tests/test_n8n.py`; their
behaviour is not.
